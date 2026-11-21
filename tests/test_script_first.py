"""Sentence integrity, script/footage agreement and saved analysis upgrades."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from pyscenedetect_demo.contract.validator import ROOT, read_json, resolve
from pyscenedetect_demo.editor.clip_analysis import cache_path, seed_saved_analysis
from pyscenedetect_demo.editor.plans import accept_plan
from pyscenedetect_demo.editor.prompting import build_prompt
from pyscenedetect_demo.editor.segmentation import build_units
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.storage import write_json


class ScriptFirstTests(unittest.TestCase):
    def test_new_prompt_requires_script_while_saved_selections_remain_supported(self):
        analysis = read_json(ROOT / "examples/llm-input.json")
        prompt = build_prompt(analysis, {})
        schema = json.loads(prompt.split("REQUIRED RESPONSE JSON SCHEMA\n", 1)[1].split(
            "\n\nANALYSIS INPUT", 1)[0])
        self.assertIn("script", schema["required"])
        resolve(analysis, read_json(ROOT / "examples/llm-edit-plan.json"),
                read_json(ROOT / "examples/private-source-map.json"))

    def test_script_mismatch_preserves_the_previously_accepted_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_json(folder / "project.json", {"status": "analyzed"})
            write_json(folder / "analysis.json", read_json(ROOT / "examples/llm-input.json"))
            write_json(folder / "private-source-map.json", read_json(ROOT / "examples/private-source-map.json"))
            plan = read_json(ROOT / "examples/llm-edit-plan.json")
            accepted = accept_plan(folder, json.dumps(plan))
            previous = (folder / "project.json").read_bytes()
            plan["script"] = accepted["script"].replace("not fix", "fix")
            with self.assertRaisesRegex(ValueError, "Script does not match"):
                accept_plan(folder, json.dumps(plan))
            self.assertEqual((folder / "project.json").read_bytes(), previous)

    def test_long_sentence_stays_whole_across_filler_pause_and_old_limits(self):
        text = "We need um to keep the entire explanation because removing this part would change what the speaker actually means."
        words = [{"word": word, "start": i * .5 + (1 if i > 6 else 0),
                  "end": i * .5 + (1 if i > 6 else 0) + .3}
                 for i, word in enumerate(text.split())]
        units = build_units(words, 12000)
        speech = [unit for unit in units if unit["kind"] == "speech"]
        self.assertEqual([unit["text"] for unit in speech], [text])
        self.assertEqual(units[0]["start_ms"], 0)
        self.assertEqual(units[-1]["end_ms"], 12000)
        for left, right in zip(units, units[1:]):
            self.assertEqual(left["end_ms"], right["start_ms"])

    def test_missing_punctuation_is_not_permission_to_cut_a_sentence(self):
        units = build_units([{"word": str(i), "start": i, "end": i + .4} for i in range(30)], 31000)
        self.assertEqual(len([unit for unit in units if unit["kind"] == "speech"]), 1)

    def test_semicolon_and_title_do_not_end_sentence(self):
        words = ["Dr.", "Khan", "explains;", "please", "listen.", "Next", "point!"]
        units = build_units([{"word": word, "start": i * .3, "end": i * .3 + .2}
                             for i, word in enumerate(words)], 2400)
        self.assertEqual([unit["text"] for unit in units if unit["kind"] == "speech"],
                         ["Dr. Khan explains; please listen.", "Next point!"])

    def test_urdu_and_quoted_sentence_endings(self):
        for ending in ["۔", "؟", ".\"", "!”", "।", "。"]:
            with self.subTest(ending=ending):
                units = build_units([{"word": "first" + ending, "start": 0, "end": .5},
                                     {"word": "second.", "start": .8, "end": 1.3}], 1500)
                self.assertEqual(len([unit for unit in units if unit["kind"] == "speech"]), 2)

    def test_script_must_match_footage_verbatim_but_allows_line_breaks(self):
        analysis = read_json(ROOT / "examples/llm-input.json")
        plan = read_json(ROOT / "examples/llm-edit-plan.json")
        mapping = read_json(ROOT / "examples/private-source-map.json")
        script = resolve(analysis, plan, mapping)["script"]
        plan["script"] = script.replace(" ", "\n")
        original = copy.deepcopy(plan)
        self.assertEqual(resolve(analysis, plan, mapping)["script"], script)
        self.assertEqual(plan, original)
        for replacement in [script.replace("not fix", "fix"), script + " Invented ending.", ""]:
            plan["script"] = replacement
            with self.subTest(script=replacement), self.assertRaisesRegex(ValueError, "Script does not match"):
                resolve(analysis, plan, mapping)

    def test_saved_word_timings_regroup_fragments_without_transcribing_again(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            settings = AppSettings()
            asset = {"id": "asset_1", "sha256": "saved-source", "duration_ms": 2000}
            state = {"assets": [asset], "describe_visuals": True}
            write_json(folder / "project.json", state)
            fragments = [
                {"id": "u1", "start_ms": 0, "end_ms": 1000, "kind": "speech", "text": "This is",
                 "visual_description": "Presenter", "boundary_quality": "candidate"},
                {"id": "u2", "start_ms": 1000, "end_ms": 2000, "kind": "speech", "text": "one sentence.",
                 "visual_description": "Presenter", "boundary_quality": "candidate"},
            ]
            write_json(folder / "analysis.json", {"units": fragments, "analysis_complete": True})
            write_json(folder / "private-source-map.json", {"assets": {"asset_1": {"duration_ms": 2000}},
                       "units": {unit["id"]: {"asset_id": "asset_1", "in_ms": unit["start_ms"],
                                               "out_ms": unit["end_ms"]} for unit in fragments}})
            words = [{"word": word, "start": i * .5, "end": i * .5 + .4}
                     for i, word in enumerate("This is one sentence.".split())]
            write_json(folder / "words.json", {"asset_1": {"language": "en", "words": words}})
            seed_saved_analysis(folder, state, settings)
            result = read_json(cache_path(folder, asset, state, settings))
            self.assertEqual([unit["text"] for unit in result["units"]], ["This is one sentence."])
            self.assertEqual(result["units"][0]["visual_description"], "Presenter")
            self.assertEqual(result["words"]["words"], words)


if __name__ == "__main__":
    unittest.main()
