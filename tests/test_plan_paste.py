"""Clipboard formatting must not alter JSON values or relax plan validation."""

import json
import tempfile
import unittest
from pathlib import Path

from pyscenedetect_demo.contract import RESOURCES
from pyscenedetect_demo.editor.plans import accept_plan, parse_plan_text
from pyscenedetect_demo.storage import read_json, write_json


def copied(text, newline="\n", entity="&#x20;"):
    return text.replace("\n", "\\" + newline + entity)


class ClipboardParsingTests(unittest.TestCase):
    def test_exact_reported_clipboard_response(self):
        raw = (Path(__file__).parent / "fixtures/chatgpt-clipboard-plan.txt").read_text(encoding="utf-8")
        expected = {
            "version": "2.0",
            "input_id": "4952f1cacccf82183e42d1baf0d787617262f01a10cb20ee98c4f27030cd2fca",
            "sequence": [{"unit_ids": ids} for ids in [
                ["u00001"], ["u00007", "u00011"], ["u00017"], ["u00019", "u00020", "u00022"],
            ]],
            "removed_unit_ids": [f"u{number:05d}" for number in [
                2, 3, 4, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 18, 21, 23,
            ]],
        }
        self.assertEqual(parse_plan_text(raw), expected)
        self.assertEqual(parse_plan_text(json.dumps(expected, indent=2)), expected)

    def test_plain_and_fenced_copies_with_windows_or_unix_line_breaks(self):
        plan = read_json(RESOURCES / "examples/llm-edit-plan.json")
        text = json.dumps(plan, indent=2)
        for newline in ("\n", "\r\n"):
            for entity in ("&#x20;", "&#32;", "&#X20;", "&nbsp;", ""):
                for fence in ("", "```json", "```"):
                    with self.subTest(newline=newline, entity=entity, fence=fence):
                        raw = copied(text, newline, entity)
                        if fence:
                            raw = fence + newline + raw + newline + "```"
                        self.assertEqual(parse_plan_text(raw), plan)

    def test_markdown_line_breaks_on_code_fences(self):
        raw = copied('```json\n{\n  "version": "2.0"\n}\n```', entity="")
        self.assertEqual(parse_plan_text(raw), {"version": "2.0"})

    def test_json_strings_keep_entities_backslashes_quotes_and_unicode(self):
        value = {"text": 'Keep &#x20; &nbsp; &quot; \\ and "quotes"\nاردو', "path": r"C:\new\test.mp4"}
        text = json.dumps(value, indent=2, ensure_ascii=False)
        self.assertEqual(parse_plan_text(text), value)
        self.assertEqual(parse_plan_text(copied(text)), value)

    def test_duplicate_keys_and_nonfinite_numbers_still_rejected(self):
        for text in ('{\n"version":"2.0", "version":"2.0"\n}',
                     '{\n"version":"2.0", "\\u0076ersion":"2.0"\n}'):
            for raw in (text, copied(text)):
                with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                    parse_plan_text(raw)
        for number in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(number=number), self.assertRaisesRegex(ValueError, "Invalid JSON number"):
                parse_plan_text(copied('{\n"number":' + number + '\n}'))

    def test_other_malformed_json_is_not_repaired(self):
        for text in ("{\n'version': '2.0'\n}", '{\n"version": "2.0",\n}',
                     '{\n"version": "2.0"\n', '{\n"text": "broken\nstring"\n}',
                     '{\n"version": &quot;2.0&quot;\n}', '{\n"text": "broken\\\nstring"\n}'):
            with self.subTest(text=text), self.assertRaises(json.JSONDecodeError):
                parse_plan_text(copied(text))


class PastedPlanAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        for source, target in (("llm-input.json", "analysis.json"),
                               ("private-source-map.json", "private-source-map.json")):
            write_json(self.folder / target, read_json(RESOURCES / "examples" / source))
        write_json(self.folder / "project.json", {"status": "analyzed"})
        self.plan = read_json(RESOURCES / "examples/llm-edit-plan.json")

    def test_copy_button_and_manual_copy_publish_identical_plans(self):
        plain = json.dumps(self.plan, indent=2)
        expected = accept_plan(self.folder, plain)
        revision = read_json(self.folder / "project.json")["plan_revision"]
        result = accept_plan(self.folder, copied(plain, "\r\n"))
        self.assertEqual(result, expected)
        self.assertEqual(read_json(self.folder / "plan.json"), self.plan)
        self.assertEqual(read_json(self.folder / "project.json")["plan_revision"], revision)

    def test_copied_invalid_plans_do_not_replace_saved_plan(self):
        accept_plan(self.folder, json.dumps(self.plan))
        previous = (self.folder / "project.json").read_bytes()
        previous_plan = (self.folder / "plan.json").read_bytes()
        variants = [
            {**self.plan, "input_id": "stale"},
            {**self.plan, "sequence": [{"unit_ids": ["invented"]}]},
            {**self.plan, "extra": "not allowed"},
        ]
        for plan in variants:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                accept_plan(self.folder, copied(json.dumps(plan, indent=2)))
            self.assertEqual((self.folder / "project.json").read_bytes(), previous)
            self.assertEqual((self.folder / "plan.json").read_bytes(), previous_plan)
