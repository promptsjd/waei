"""Real local uploads, analysis, JSON handover and MP4 rendering. No LLM calls."""
import copy
import json
import os
import time
from pathlib import Path

import requests

from pyscenedetect_demo.editing import probe, run_command

ROOT = Path(__file__).resolve().parent
from pyscenedetect_demo.settings import AppSettings
SETTINGS = AppSettings.from_env()
URL = os.environ.get('SCENE_SCRIBE_URL', f'http://{SETTINGS.host}:{SETTINGS.port}')
OUTPUT_ROOT = SETTINGS.output_root.resolve()


def checked(method, path, **kwargs):
    response = requests.request(method, URL + path, timeout=60, **kwargs)
    if not response.ok:
        raise RuntimeError(f'{response.status_code}: {response.text}')
    return response


def wait_for(project_id, expected):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = checked('GET', '/api/editor/projects/' + project_id).json()
        if state['status'] == 'failed':
            raise RuntimeError(state['error'])
        if state['status'] == expected:
            return state
        time.sleep(1)
    raise TimeoutError('Editor processing did not finish in 15 minutes')


def run_case(paths, visuals, keep_silence=False):
    start = time.perf_counter()
    handles = [path.open('rb') for path in paths]
    try:
        response = checked('POST', '/api/editor/projects',
            files=[('videos', (path.name, handle, 'video/mp4')) for path, handle in zip(paths, handles)],
            data={'topic': 'Useful recording advice' if visuals else '',
                  'context': 'Practical tips for recording a talking-head video.' if visuals else '', 'describe_visuals': str(visuals).lower(), 'language': 'en'})
    finally:
        for handle in handles:
            handle.close()
    project_id = response.json()['id']
    print('Testing multi-clip project', project_id, flush=True)
    state = wait_for(project_id, 'analyzed')
    analysis = state['analysis']
    prompt = checked('GET', f'/api/editor/projects/{project_id}/prompt').text
    assert analysis['input_id'] in prompt
    assert 'REQUIRED RESPONSE JSON SCHEMA' in prompt
    assert 'private-source-map' not in prompt
    for forbidden in ['goal', 'audience', 'style', 'target_duration_ms', 'target_seconds',
                      'reason', 'reason_code', 'note', 'summary', 'review_items', 'joins']:
        assert '"' + forbidden + '"' not in prompt, forbidden
    assert analysis['version'] == '2.0'
    assert analysis['topic'] == ('Useful recording advice' if visuals else '')
    assert analysis['allow_reorder'] is False
    if not visuals:
        assert all(unit['visual_description'] is None for unit in analysis['units'])
    for path in paths:
        assert path.name not in prompt, 'Filename leaked into LLM prompt'
    folder = OUTPUT_ROOT / 'editor' / project_id
    mapping = json.loads((folder / 'private-source-map.json').read_text(encoding='utf-8'))
    assert len(mapping['assets']) == 2
    if visuals:
        assert any(unit['visual_description'] for unit in analysis['units'])
    chosen = []
    for asset_index, asset in enumerate(state['assets']):
        available = [unit for unit in analysis['units'] if mapping['units'][unit['id']]['asset_id'] == asset['id']]
        speech = [unit for unit in available if unit['kind'] == 'speech' and unit['text']]
        if speech:
            chosen.append(speech[0]['id'])
        elif keep_silence:
            chosen.append(available[0]['id'])
    assert len(chosen) == 2, chosen
    # This response fixture tests the handover and renderer, not LLM judgment.
    plan = {'version': '2.0', 'input_id': analysis['input_id'],
            'sequence': [{'unit_ids': [unit_id]} for unit_id in chosen],
            'removed_unit_ids': [unit['id'] for unit in analysis['units'] if unit['id'] not in chosen]}
    bad = copy.deepcopy(plan)
    bad['input_id'] = 'stale-input'
    rejected = requests.post(URL + f'/api/editor/projects/{project_id}/plan', json=bad, timeout=30)
    assert rejected.status_code == 400, rejected.text
    bad = copy.deepcopy(plan)
    bad['sequence'][0]['unit_ids'][0] = 'invented-id'
    rejected = requests.post(URL + f'/api/editor/projects/{project_id}/plan', json=bad, timeout=30)
    assert rejected.status_code == 400, rejected.text
    resolved = checked('POST', f'/api/editor/projects/{project_id}/plan', json=plan).json()
    assert len(resolved['timeline']) == 2
    assert resolved['status'] == 'needs_review'
    assert not resolved['render_allowed']
    checked('POST', f'/api/editor/projects/{project_id}/render')
    state = wait_for(project_id, 'completed')
    assert state['render_is_preview']
    video = checked('GET', f'/api/editor/projects/{project_id}/video?download=true')
    assert video.headers['content-type'] == 'video/mp4'
    assert 'edited.mp4' in video.headers['content-disposition']
    ranged = requests.get(URL + f'/api/editor/projects/{project_id}/video', headers={'Range': 'bytes=0-99'}, timeout=30)
    assert ranged.status_code == 206 and len(ranged.content) == 100
    output = folder / state['output_file']
    actual = probe(output)
    assert actual['has_audio']
    assert abs(actual['duration_ms'] - resolved['duration_ms']) <= 200
    run_command(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 'null', '-'])
    details = json.loads(run_command(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(output)]))
    streams = {stream['codec_type']: stream for stream in details['streams']}
    assert abs(float(streams['audio']['duration']) - float(streams['video']['duration'])) < .15
    result = {'project_id': project_id, 'clips': len(paths), 'scene_descriptions': visuals,
              'unit_count': len(analysis['units']), 'retained_ms': resolved['duration_ms'],
              'rendered_ms': actual['duration_ms'], 'seconds': round(time.perf_counter() - start, 2),
              'url': URL + '/editor?project=' + project_id}
    print('PASS:', json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    page = checked('GET', '/editor')
    assert 'id="editor-files"' in page.text and 'accept=".mp4" multiple' in page.text and 'editor.js' in page.text
    for sample in ['speech-demo.mp4', 'speech-demo-second.mp4']:
        checked('GET', '/api/editor/samples/' + sample)
    first = run_case([ROOT / 'samples/speech-demo.mp4', ROOT / 'samples/speech-demo-second.mp4'], True)
    test_assets = OUTPUT_ROOT / 'editor-test-assets'
    test_assets.mkdir(exist_ok=True)
    portrait = test_assets / 'portrait-silent.mp4'
    run_command(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=320x568:r=24:d=1.5',
                 '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(portrait)])
    second = run_case([ROOT / 'samples/speech-demo.mp4', portrait], False, keep_silence=True)
    (OUTPUT_ROOT / 'editor-test-results.json').write_text(json.dumps([first, second], indent=2), encoding='utf-8')
