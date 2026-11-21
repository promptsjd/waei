import unittest
import copy

from pyscenedetect_demo.contract.validator import ROOT, read_json, resolve


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.analysis = read_json(ROOT / "examples/v1/llm-input.json")
        self.plan = read_json(ROOT / "examples/v1/llm-edit-plan.json")
        self.mapping = read_json(ROOT / "examples/v1/private-source-map.json")

    def run_plan(self):
        return resolve(self.analysis, self.plan, self.mapping)

    def test_multi_source_resolution_and_original_script(self):
        result = self.run_plan()
        self.assertEqual(result["duration_ms"], 15000)
        self.assertEqual(result["removed_duration_ms"], 7000)
        self.assertEqual(
            [(row["asset_id"], row["in_ms"], row["out_ms"]) for row in result["timeline"]],
            [("asset_A", 2000, 6000), ("asset_B", 0, 11000)],
        )
        self.assertEqual(result["timeline"][1]["output_in_ms"], 4000)
        self.assertIn("will not fix", result["script"])
        self.assertFalse(result["render_allowed"])

    def test_unknown_id_rejected(self):
        self.plan["sequence"][0]["unit_ids"] = ["invented"]
        with self.assertRaisesRegex(ValueError, "unknown unit"):
            self.run_plan()

    def use_gapped_group(self):
        self.plan["sequence"] = [
            {"unit_ids": ["u002", "u004", "u005", "u006"], "reason": "Keep the selected advice."}
        ]
        self.plan["joins"] = []
        self.plan["review_items"] = []
        self.plan["status"] = "ready"

    def test_gapped_group_splits_without_restoring_omitted_units(self):
        self.use_gapped_group()
        original = copy.deepcopy(self.plan)
        result = self.run_plan()
        self.assertEqual(self.plan, original)
        self.assertEqual(
            [unit_id for row in result["timeline"] for unit_id in row["unit_ids"]],
            ["u002", "u004", "u005", "u006"],
        )
        self.assertEqual(result["duration_ms"], 15000)
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["render_allowed"])
        self.assertEqual(len(result["review_items"]), 1)
        self.assertEqual(result["review_items"][0]["unit_ids"], ["u002", "u004"])
        self.assertEqual(len(result["joins"]), 1)

    def test_gapped_group_splits_even_within_same_asset(self):
        self.use_gapped_group()
        self.mapping["assets"] = {"one_asset": {"duration_ms": 22000}}
        self.mapping["units"] = {
            unit["id"]: {"asset_id": "one_asset", "in_ms": unit["start_ms"], "out_ms": unit["end_ms"]}
            for unit in self.analysis["units"]
        }
        result = self.run_plan()
        self.assertEqual(
            [(row["in_ms"], row["out_ms"]) for row in result["timeline"]], [(2000, 6000), (9000, 20000)]
        )
        self.assertNotIn("u003", [unit_id for row in result["timeline"] for unit_id in row["unit_ids"]])
        self.assertEqual(len(result["review_items"]), 1)

    def test_split_inside_group_preserves_original_between_group_join(self):
        self.plan["sequence"] = [
            {"unit_ids": ["u002", "u004"], "reason": "Selected opening."},
            {"unit_ids": ["u005", "u006"], "reason": "Selected ending."},
        ]
        self.plan["joins"][0]["note"] = "Original between-group connection note."
        self.plan["review_items"] = []
        result = self.run_plan()
        self.assertEqual(
            [(join["from_index"], join["to_index"]) for join in result["joins"]], [(0, 1), (1, 2)]
        )
        self.assertEqual(result["joins"][1]["note"], "Original between-group connection note.")
        self.assertTrue(all(join["review_required"] for join in result["joins"]))

    def test_reordered_units_inside_group_still_require_permission(self):
        self.use_gapped_group()
        self.plan["sequence"][0]["unit_ids"] = ["u004", "u005", "u006", "u002"]
        with self.assertRaisesRegex(ValueError, "Reordering is disabled"):
            self.run_plan()

    def test_permitted_reordered_units_inside_group_keep_submitted_order(self):
        self.use_gapped_group()
        self.analysis["brief"]["allow_reorder"] = True
        self.plan["sequence"][0]["unit_ids"] = ["u004", "u005", "u006", "u002"]
        result = self.run_plan()
        self.assertEqual(
            [unit_id for row in result["timeline"] for unit_id in row["unit_ids"]],
            ["u004", "u005", "u006", "u002"],
        )
        self.assertEqual(result["review_items"][0]["unit_ids"], ["u006", "u002"])

    def test_multiple_gaps_create_distinct_reviewed_cuts(self):
        self.use_gapped_group()
        self.plan["sequence"][0]["unit_ids"].remove("u005")
        self.plan["removed"].append(
            {"unit_id": "u005", "reason_code": "not_selected", "reason": "Not selected."}
        )
        self.analysis["brief"]["target_duration_ms"] = None
        result = self.run_plan()
        self.assertEqual(len(result["timeline"]), 3)
        self.assertEqual(
            [item["unit_ids"] for item in result["review_items"]], [["u002", "u004"], ["u004", "u006"]]
        )

    def test_needs_review_gapped_group_can_supply_no_redundant_notes(self):
        self.use_gapped_group()
        self.plan["status"] = "needs_review"
        result = self.run_plan()
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(len(result["review_items"]), 1)

    def test_missing_decision_rejected(self):
        self.plan["removed"].pop()
        with self.assertRaisesRegex(ValueError, "unclassified"):
            self.run_plan()

    def test_duplicate_kept_removed_rejected(self):
        self.plan["removed"][0]["unit_id"] = "u002"
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.run_plan()

    def test_required_material_cannot_be_removed(self):
        self.analysis["brief"]["required_unit_ids"] = ["u001"]
        with self.assertRaisesRegex(ValueError, "required unit"):
            self.run_plan()

    def test_disallowed_reorder_rejected(self):
        self.plan["sequence"].reverse()
        with self.assertRaisesRegex(ValueError, "Reordering is disabled"):
            self.run_plan()

    def test_allowed_reorder_resolves_original_sources(self):
        self.analysis["brief"]["allow_reorder"] = True
        self.plan["sequence"].reverse()
        self.plan["review_items"][0]["unit_ids"] = ["u006", "u002"]
        result = self.run_plan()
        self.assertEqual(result["timeline"][0]["asset_id"], "asset_B")
        self.assertEqual(result["timeline"][1]["output_in_ms"], 11000)

    def test_invented_timestamps_or_extra_fields_rejected(self):
        self.plan["sequence"][0]["start_ms"] = 1234
        with self.assertRaisesRegex(ValueError, "Additional properties"):
            self.run_plan()

    def test_stale_plan_rejected(self):
        self.plan["input_id"] = "old-analysis"
        with self.assertRaisesRegex(ValueError, "input_id"):
            self.run_plan()

    def test_incomplete_analysis_requires_explicit_review(self):
        self.analysis["analysis_complete"] = False
        with self.assertRaisesRegex(ValueError, "incomplete_analysis"):
            self.run_plan()

    def test_uncertain_boundary_requires_explicit_review(self):
        self.analysis["units"][1]["boundary_quality"] = "uncertain"
        with self.assertRaisesRegex(ValueError, "uncertain_boundary"):
            self.run_plan()

    def test_out_of_bounds_source_rejected(self):
        self.mapping["units"]["u002"]["out_ms"] = 20000
        with self.assertRaisesRegex(ValueError, "outside asset bounds"):
            self.run_plan()

    def test_duration_mismatch_rejected(self):
        self.mapping["units"]["u002"]["out_ms"] = 5000
        with self.assertRaisesRegex(ValueError, "duration mismatch"):
            self.run_plan()

    def test_target_miss_cannot_be_silently_accepted(self):
        self.analysis["brief"]["target_duration_ms"] = 5000
        with self.assertRaisesRegex(ValueError, "target_unmet"):
            self.run_plan()

    def test_gap_in_virtual_timeline_rejected(self):
        self.analysis["units"][1]["start_ms"] = 2001
        with self.assertRaisesRegex(ValueError, "without gaps"):
            self.run_plan()

    def test_broken_join_rejected(self):
        self.plan["joins"] = []
        with self.assertRaisesRegex(ValueError, "Joins must connect"):
            self.run_plan()

    def test_review_cannot_be_mislabeled_ready(self):
        self.plan["status"] = "ready"
        self.plan["joins"][0]["review_required"] = False
        with self.assertRaisesRegex(ValueError, "ready plan cannot"):
            self.run_plan()

    def test_flagged_join_generates_missing_review_item(self):
        self.plan["review_items"] = []
        original = copy.deepcopy(self.plan)
        result = self.run_plan()
        self.assertEqual(self.plan, original)
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["render_allowed"])
        self.assertEqual(
            result["review_items"],
            [
                {
                    "unit_ids": ["u002", "u004"],
                    "issue_code": "join_risk",
                    "note": self.plan["joins"][0]["note"],
                }
            ],
        )
        self.assertTrue(result["joins"][0]["review_required"])

    def test_flagged_join_promotes_ready_without_losing_warning(self):
        self.plan["status"] = "ready"
        self.plan["review_items"] = []
        result = self.run_plan()
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["render_allowed"])
        self.assertEqual(result["review_items"][0]["unit_ids"], ["u002", "u004"])

    def test_existing_matching_join_review_is_not_duplicated(self):
        result = self.run_plan()
        self.assertEqual(len(result["review_items"]), 1)
        self.assertEqual(result["review_items"], self.plan["review_items"])

    def test_review_for_another_pair_does_not_hide_flagged_join(self):
        self.plan["review_items"][0]["unit_ids"] = ["u001", "u003"]
        result = self.run_plan()
        self.assertEqual(len(result["review_items"]), 2)
        self.assertEqual(result["review_items"][1]["unit_ids"], ["u002", "u004"])

    def test_auto_review_does_not_accept_unknown_review_ids(self):
        self.plan["review_items"][0]["unit_ids"] = ["invented-id"]
        with self.assertRaisesRegex(ValueError, "Review references unknown"):
            self.run_plan()

    def test_ready_plan_can_be_resolved(self):
        # This tests the contract mechanics, not editorial or visual correctness.
        self.plan["review_items"] = []
        self.plan["joins"][0]["review_required"] = False
        self.plan["status"] = "ready"
        self.assertTrue(self.run_plan()["render_allowed"])

    def test_missing_transcript_cannot_be_treated_as_silence(self):
        self.analysis["units"][0]["text"] = ""
        with self.assertRaisesRegex(ValueError, "uncertain_transcript"):
            self.run_plan()

    def test_hidden_source_change_generates_review_even_in_single_run(self):
        self.plan["sequence"] = [
            {"unit_ids": ["u002", "u003", "u004", "u005", "u006"], "reason": "Keep continuous advice."}
        ]
        self.plan["removed"] = [item for item in self.plan["removed"] if item["unit_id"] != "u003"]
        self.plan["joins"] = []
        self.plan["review_items"] = []
        self.plan["status"] = "ready"
        self.analysis["brief"]["target_duration_ms"] = 18000
        result = self.run_plan()
        self.assertEqual(len(result["timeline"]), 2)
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["render_allowed"])
        self.assertEqual(result["review_items"][0]["unit_ids"], ["u003", "u004"])
        self.assertEqual(len(result["joins"]), 1)


if __name__ == "__main__":
    unittest.main()
