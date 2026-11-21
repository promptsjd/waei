import copy
import unittest

from pyscenedetect_demo.contract.validator import ROOT, check_schema, read_json, resolve


class CompactContractTests(unittest.TestCase):
    def setUp(self):
        self.analysis = read_json(ROOT / "examples/llm-input.json")
        self.plan = read_json(ROOT / "examples/llm-edit-plan.json")
        self.mapping = read_json(ROOT / "examples/private-source-map.json")

    def run_plan(self):
        return resolve(self.analysis, self.plan, self.mapping)

    def test_selection_needs_no_annotations_and_preserves_verbatim_script(self):
        original = copy.deepcopy(self.plan)
        result = self.run_plan()
        self.assertEqual(result["duration_ms"], 15000)
        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(len(result["joins"]), 1)
        self.assertIn("will not fix a very noisy room", result["script"])
        self.assertNotIn("charge my phone", result["script"])
        self.assertEqual(self.plan, original)

    def test_optional_subject_fields_can_be_blank_or_absent(self):
        self.analysis.update(topic="", context="")
        self.run_plan()
        del self.analysis["topic"], self.analysis["context"]
        self.run_plan()

    def test_old_project_accepts_compact_response_without_old_target_rules(self):
        self.analysis = read_json(ROOT / "examples/v1/llm-input.json")
        self.mapping = read_json(ROOT / "examples/v1/private-source-map.json")
        self.plan["input_id"] = self.analysis["input_id"]
        self.analysis["brief"]["target_duration_ms"] = 1000
        self.assertEqual(self.run_plan()["duration_ms"], 15000)

    def test_gapped_group_preserves_selection_and_compiles_actual_connections(self):
        self.plan["sequence"] = [{"unit_ids": ["u002", "u004", "u005", "u006"]}]
        result = self.run_plan()
        self.assertEqual(
            [row["unit_ids"] for row in result["timeline"]], [["u002"], ["u004", "u005", "u006"]]
        )
        self.assertEqual([(join["from_index"], join["to_index"]) for join in result["joins"]], [(0, 1)])

    def test_adjacent_groups_merge_into_one_physical_range(self):
        self.plan["sequence"] = [{"unit_ids": [uid]} for uid in ["u002", "u004", "u005", "u006"]]
        result = self.run_plan()
        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["timeline"][1]["unit_ids"], ["u004", "u005", "u006"])

    def test_reordering_requires_permission_and_never_sorts_the_selection(self):
        self.plan["sequence"].reverse()
        with self.assertRaisesRegex(ValueError, "Reordering is disabled"):
            self.run_plan()
        self.analysis["allow_reorder"] = True
        result = self.run_plan()
        self.assertEqual(result["timeline"][0]["unit_ids"], ["u004", "u005", "u006"])
        self.assertTrue(result["script"].startswith("Place the microphone"))

    def test_duplicate_unclassified_unknown_and_stale_decisions_are_rejected(self):
        original = copy.deepcopy(self.plan)
        for mutation, message in [
            (lambda p: p["removed_unit_ids"].append("u002"), "exactly once"),
            (lambda p: p["removed_unit_ids"].pop(), "unclassified"),
            (lambda p: p["removed_unit_ids"].append("invented"), "unknown unit"),
            (lambda p: p.update(input_id="old"), "mismatched"),
        ]:
            with self.subTest(message=message):
                self.plan = copy.deepcopy(original)
                mutation(self.plan)
                with self.assertRaisesRegex(ValueError, message):
                    self.run_plan()

    def test_required_material_and_private_media_bounds_still_enforced(self):
        self.plan["sequence"][1]["unit_ids"].remove("u006")
        self.plan["removed_unit_ids"].append("u006")
        with self.assertRaisesRegex(ValueError, "required unit"):
            self.run_plan()
        self.plan = read_json(ROOT / "examples/llm-edit-plan.json")
        self.mapping["units"]["u002"]["out_ms"] = 1000000
        with self.assertRaisesRegex(ValueError, "outside asset bounds"):
            self.run_plan()

    def test_uncertain_analysis_is_handled_locally_without_llm_notes(self):
        self.analysis["analysis_complete"] = False
        self.analysis["units"][1].update(text="", boundary_quality="uncertain")
        result = self.run_plan()
        self.assertEqual(result["status"], "needs_review")
        codes = {item["issue_code"] for item in result["review_items"]}
        self.assertTrue({"incomplete_analysis", "uncertain_transcript", "uncertain_boundary"} <= codes)

    def test_empty_selection_is_valid_but_has_no_renderable_timeline(self):
        self.analysis["required_unit_ids"] = []
        self.plan.update(sequence=[], removed_unit_ids=[unit["id"] for unit in self.analysis["units"]])
        result = self.run_plan()
        self.assertEqual(result["timeline"], [])
        self.assertFalse(result["render_allowed"])

    def test_response_rejects_extra_annotations_and_non_object_json(self):
        self.plan["sequence"][0]["reason"] = "Unneeded annotation"
        with self.assertRaises(ValueError):
            self.run_plan()
        for value in [None, [], "invalid", 42]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                check_schema(value, "edit-plan.schema.json")


if __name__ == "__main__":
    unittest.main()
