"""Exercise the running local web app with the included sample clips."""
import argparse
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
from pyscenedetect_demo.settings import AppSettings
SETTINGS = AppSettings.from_env()
URL = os.environ.get('SCENE_SCRIBE_URL', f'http://{SETTINGS.host}:{SETTINGS.port}')
OUTPUT_ROOT = SETTINGS.output_root.resolve()


def run(video, mode='analyze', vision=False, transcribe=False):
    start = time.perf_counter()
    with (ROOT / 'samples' / video).open('rb') as handle:
        response = requests.post(URL + '/api/jobs',
            files={'video': (video, handle, 'video/mp4')},
            data={'mode': mode, 'describe_visuals': str(vision).lower(),
                  'transcribe': str(transcribe).lower(), 'asr_model': 'tiny'}, timeout=30)
    response.raise_for_status()
    job_id = response.json()['job_id']
    print('Testing', video, mode, 'job', job_id, flush=True)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        response = requests.get(URL + '/api/jobs/' + job_id, timeout=30)
        response.raise_for_status()
        job = response.json()
        if job['status'] == 'failed':
            raise RuntimeError(job['error'])
        if job['status'] == 'completed':
            break
        time.sleep(1)
    else:
        raise TimeoutError('Job exceeded 30 minutes')
    endpoint = '/shots' if mode == 'shotlist' else '/scenes'
    response = requests.get(URL + '/api/jobs/' + job_id + endpoint, timeout=30)
    response.raise_for_status()
    result = response.json()
    records = result['shots' if mode == 'shotlist' else 'scenes']
    expected = 3 if video == 'three-scenes.mp4' else 1
    assert len(records) == expected, (len(records), expected)
    output = Path(job['output_dir'])
    for record in records:
        for key in ('screenshot_path', 'audio_path', 'start_frame_path', 'end_frame_path'):
            if record.get(key):
                assert (output / record[key]).is_file(), record[key]
        if vision:
            assert record['visual_description'].strip(), 'Empty caption'
            print('Caption:', record['visual_description'], flush=True)
        if video == 'speech-demo.mp4' and transcribe:
            assert record['dialogue'].strip(), 'Empty speech transcript'
            print('Transcript:', record['dialogue'], flush=True)
    elapsed = round(time.perf_counter() - start, 2)
    print('PASS:', len(records), 'scenes;', elapsed, 'seconds;', URL + '/jobs/' + job_id, flush=True)
    return {'video': video, 'mode': mode, 'vision': vision, 'transcribe': transcribe,
            'seconds': elapsed, 'job_id': job_id, 'output': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vision', action='store_true')
    parser.add_argument('--transcribe', action='store_true')
    options = parser.parse_args()
    results = [run('three-scenes.mp4'), run('three-scenes.mp4', mode='shotlist')]
    if options.vision or options.transcribe:
        results.append(run('car-demo.mp4', vision=options.vision, transcribe=options.transcribe))
    if options.transcribe:
        results.append(run('speech-demo.mp4', transcribe=True))
    (OUTPUT_ROOT / 'test-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
