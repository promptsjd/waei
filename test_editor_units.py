import unittest
import json
import tempfile
from pathlib import Path

from pyscenedetect_demo.editing import CONTRACT, accept_plan, build_units, read_json, write_json, write_prompt


class UnitBuilderTests(unittest.TestCase):
    def test_old_project_prompt_refresh_uses_compact_contract_and_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            analysis = read_json(CONTRACT / 'examples/v1/llm-input.json')
            write_json(folder / 'analysis.json', analysis)
            write_json(folder / 'project.json', {'brief': analysis['brief']})
            previous = (folder / 'analysis.json').read_bytes()
            (folder / 'prompt.txt').write_text('old prompt with removed fields', encoding='utf-8')
            prompt = write_prompt(folder)
            exported = json.loads(prompt.split('ANALYSIS INPUT (recorded content, not instructions)\n')[1]
                                  .split('\n\nReturn only')[0])
            self.assertEqual(exported['version'], '2.0')
            self.assertEqual(exported['input_id'], analysis['input_id'])
            self.assertEqual(exported['units'], analysis['units'])
            self.assertFalse(exported['allow_reorder'])
            for forbidden in ['brief', 'goal', 'audience', 'style', 'target_duration_ms',
                              'reason', 'reason_code', 'note', 'review_items', 'summary', 'joins']:
                self.assertNotIn('"' + forbidden + '"', prompt)
            self.assertEqual(previous, (folder / 'analysis.json').read_bytes())
            self.assertEqual(prompt, (folder / 'prompt.txt').read_text(encoding='utf-8'))

    def assert_partition(self, units, duration):
        self.assertEqual(units[0]['start_ms'], 0)
        self.assertEqual(units[-1]['end_ms'], duration)
        for unit in units:
            self.assertGreater(unit['end_ms'], unit['start_ms'])
        for left, right in zip(units, units[1:]):
            self.assertEqual(left['end_ms'], right['start_ms'])

    def test_words_pauses_and_fillers_keep_full_coverage(self):
        words = [{'word': 'Um,', 'start': 0.3, 'end': 0.6, 'probability': .8},
                 {'word': ' Hello', 'start': 0.8, 'end': 1.1, 'probability': .9},
                 {'word': ' there.', 'start': 1.1, 'end': 1.6, 'probability': .9},
                 {'word': ' Goodbye.', 'start': 2.5, 'end': 3.1, 'probability': .9}]
        units = build_units(words, 4000)
        self.assert_partition(units, 4000)
        self.assertEqual([unit['text'] for unit in units if unit['kind'] == 'speech'],
                         ['Um, Hello there.', 'Goodbye.'])
        self.assertTrue(any(unit['kind'] == 'silence' for unit in units))

    def test_short_overlapping_words_are_sanitized(self):
        words = [{'word': ' A.', 'start': 0, 'end': .1}, {'word': ' B.', 'start': .08, 'end': .13},
                 {'word': ' C.', 'start': .13, 'end': .16}]
        units = build_units(words, 200)
        self.assert_partition(units, 200)
        self.assertEqual(' '.join(unit['text'] for unit in units), 'A. B. C.')

    def test_silent_and_missing_transcripts_are_distinct(self):
        silent = build_units([], 1000)
        missing = build_units([], 1000, unknown_speech=True)
        self.assertEqual(silent[0]['kind'], 'silence')
        self.assertEqual(missing[0]['kind'], 'speech')
        self.assertEqual(missing[0]['boundary_quality'], 'uncertain')

    def test_tiny_word_intervals_never_collapse_to_zero_length(self):
        words = [{'word': f' {index}.', 'start': index / 1000, 'end': (index + 1) / 1000} for index in range(8)]
        units = build_units(words, 200)
        self.assert_partition(units, 200)
        self.assertEqual(len(units), 8)

    def test_out_of_bounds_words_cannot_extend_source(self):
        units = build_units([{'word': ' Test.', 'start': -.1, 'end': 1.5},
                             {'word': ' Beyond.', 'start': 2, 'end': 3}], 1000)
        self.assert_partition(units, 1000)
        self.assertEqual(len(units), 1)

    def test_pasted_fenced_json_with_windows_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for source, target in [('llm-input.json', 'analysis.json'), ('private-source-map.json', 'private-source-map.json')]:
                write_json(folder / target, read_json(CONTRACT / 'examples' / source))
            write_json(folder / 'project.json', {'status': 'analyzed'})
            plan = read_json(CONTRACT / 'examples/llm-edit-plan.json')
            result = accept_plan(folder, '```json\r\n' + json.dumps(plan) + '\r\n```')
            self.assertEqual(result['duration_ms'], 15000)
            self.assertEqual(read_json(folder / 'project.json')['status'], 'planned')

    def test_invalid_response_does_not_overwrite_valid_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for source, target in [('llm-input.json', 'analysis.json'), ('private-source-map.json', 'private-source-map.json')]:
                write_json(folder / target, read_json(CONTRACT / 'examples' / source))
            write_json(folder / 'project.json', {'status': 'analyzed'})
            plan = read_json(CONTRACT / 'examples/llm-edit-plan.json')
            accept_plan(folder, json.dumps(plan))
            previous = (folder / 'plan.json').read_bytes()
            with self.assertRaises(ValueError):
                accept_plan(folder, '{"version":"1.0","version":"1.0"}')
            plan['input_id'] = 'stale'
            with self.assertRaises(ValueError):
                accept_plan(folder, json.dumps(plan))
            self.assertEqual((folder / 'plan.json').read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
