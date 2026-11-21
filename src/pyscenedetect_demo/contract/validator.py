"""Validate editorial JSON and resolve opaque units into source media ranges.

This produces a render plan. It does not call an LLM or modify any media.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from importlib.resources import files

from jsonschema import Draft202012Validator
from .versions import policy_for, schema_for, SUPPORTED_VERSIONS

ROOT = files(__package__)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Invalid JSON number: {value}")


def read_json(path):
    resource = path if hasattr(path, "read_text") else Path(path)
    return json.loads(
        resource.read_text(encoding="utf-8-sig"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def check_schema(value, filename):
    filename = schema_for(value.get("version") if isinstance(value, dict) else None, filename)
    schema = read_json(ROOT / filename)
    Draft202012Validator.check_schema(schema)
    error = next(iter(Draft202012Validator(schema).iter_errors(value)), None)
    if error:
        location = ".".join(map(str, error.absolute_path)) or "<root>"
        raise ValueError(f"{filename}: {location}: {error.message}")


def resolve(analysis, plan, source_map):
    check_schema(analysis, "input.schema.json")
    check_schema(plan, "edit-plan.schema.json")
    require(plan["input_id"] == analysis["input_id"], "Stale or mismatched plan input_id")
    modern = plan["version"] == "2.0"
    policy = policy_for(analysis)
    require(modern or analysis["version"] == "1.0", "Legacy plans require a legacy analysis")
    require(source_map.get("version") in SUPPORTED_VERSIONS, "Unsupported source map version")
    require(source_map.get("input_id") == analysis["input_id"], "Mismatched source map input_id")

    units = analysis["units"]
    ids = [unit["id"] for unit in units]
    require(len(set(ids)) == len(ids), "Duplicate input unit IDs")
    lookup = {unit["id"]: unit for unit in units}
    positions = {unit_id: index for index, unit_id in enumerate(ids)}
    cursor = 0
    for unit in units:
        require(
            unit["start_ms"] == cursor, "Units must partition the virtual timeline without gaps or overlaps"
        )
        require(unit["end_ms"] > unit["start_ms"], "Unit end must follow start")
        if unit["kind"] != "speech":
            require(not unit["text"].strip(), "Only speech units can contain transcript text")
        cursor = unit["end_ms"]
    require(cursor == analysis["duration_ms"], "Input duration does not match unit coverage")
    required = set(policy["required_unit_ids"])
    require(required <= set(ids), "Input references unknown required unit IDs")

    kept = [unit_id for run in plan["sequence"] for unit_id in run["unit_ids"]]
    removed = plan["removed_unit_ids"] if modern else [item["unit_id"] for item in plan["removed"]]
    all_decisions = kept + removed
    require(set(all_decisions) <= set(ids), "Plan references unknown unit IDs")
    require(len(set(all_decisions)) == len(all_decisions), "Each input unit must be classified exactly once")
    require(set(all_decisions) == set(ids), "Plan leaves input units unclassified")
    require(required <= set(kept), "Plan removes a required unit")
    if not policy["allow_reorder"]:
        indexes = [positions[unit_id] for unit_id in kept]
        require(indexes == sorted(indexes), "Reordering is disabled")

    script = " ".join(lookup[unit_id]["text"].strip() for unit_id in kept if lookup[unit_id]["text"].strip())
    if modern and "script" in plan:
        require(
            " ".join(plan["script"].split()) == " ".join(script.split()),
            "Script does not match the selected recorded speech. Return the verbatim script and matching unit IDs; "
            "do not rewrite, omit or invent spoken words.",
        )

    joins = [] if modern else plan["joins"]
    expected_joins = [(index, index + 1) for index in range(len(plan["sequence"]) - 1)]
    require(
        modern or [(join["from_index"], join["to_index"]) for join in joins] == expected_joins,
        "Joins must connect each consecutive output run exactly once, in output order",
    )
    for item in plan.get("review_items", []):
        require(set(item["unit_ids"]) <= set(ids), "Review references unknown unit IDs")

    # A flagged join already contains a review decision and its explanation.
    # Materialize its endpoint-specific review item instead of rejecting a
    # schema-valid response for omitting a redundant copy of the warning.
    # Keep the submitted plan immutable, and never clear or downgrade a warning.
    reviews = [dict(item, unit_ids=list(item["unit_ids"])) for item in plan.get("review_items", [])]

    def join_review(endpoints, note):
        matching = next(
            (
                item
                for item in reviews
                if item["issue_code"] == "join_risk" and set(endpoints) <= set(item["unit_ids"])
            ),
            None,
        )
        if matching is None:
            matching = {"unit_ids": list(endpoints), "issue_code": "join_risk", "note": note}
            reviews.append(matching)
        return matching

    flagged_joins = [join for join in joins if join["review_required"]]
    for join in flagged_joins:
        endpoints = [
            plan["sequence"][join["from_index"]]["unit_ids"][-1],
            plan["sequence"][join["to_index"]]["unit_ids"][0],
        ]
        join_review(endpoints, join["note"])
    # Grouping is presentation metadata, not an editorial decision. Preserve
    # exactly the submitted IDs and order; the source resolver below splits at
    # gaps. Never fill a gap with unselected units or sort the model's sequence.
    internal_gaps = []
    for run in plan["sequence"]:
        for left, right in zip(run["unit_ids"], run["unit_ids"][1:]):
            if positions[right] != positions[left] + 1:
                internal_gaps.append((left, right))
                join_review(
                    [left, right],
                    f"The selected units {left} and {right} have a gap or reordered connection inside a group. "
                    "The tool splits the source ranges automatically; preview this cut.",
                )
    review_status = (
        "needs_review" if flagged_joins or internal_gaps else ("ready" if modern else plan["status"])
    )
    if review_status == "ready":
        require(not reviews, "A ready plan cannot have unresolved review items")
    else:
        require(bool(reviews), "needs_review requires an explanation in review_items")

    def need_review(code, unit_ids=()):
        if modern:
            reviews.append(
                {
                    "issue_code": code,
                    "unit_ids": list(unit_ids),
                    "note": "Local analysis flagged " + code.replace("_", " ") + ".",
                }
            )
            return
        require(review_status == "needs_review", f"{code} requires needs_review status")
        require(
            any(item["issue_code"] == code and set(unit_ids) <= set(item["unit_ids"]) for item in reviews),
            f"Missing review item for {code}: {list(unit_ids)}",
        )

    if not analysis["analysis_complete"]:
        need_review("incomplete_analysis")
    for unit in units:
        if unit["kind"] == "speech" and not unit["text"].strip():
            need_review("uncertain_transcript", [unit["id"]])
    if not kept:
        need_review("insufficient_material")
    for unit_id in kept:
        if lookup[unit_id]["boundary_quality"] == "uncertain":
            need_review("uncertain_boundary", [unit_id])
    for join in joins:
        if join["review_required"]:
            endpoints = [
                plan["sequence"][join["from_index"]]["unit_ids"][-1],
                plan["sequence"][join["to_index"]]["unit_ids"][0],
            ]
            need_review("join_risk", endpoints)
    duration = sum(lookup[unit_id]["end_ms"] - lookup[unit_id]["start_ms"] for unit_id in kept)
    target = None if modern else policy["target_duration_ms"]
    if target is not None and abs(duration - target) > policy["duration_tolerance_ms"]:
        need_review("target_unmet")

    mappings = source_map.get("units", {})
    assets = source_map.get("assets", {})
    require(set(mappings) == set(ids), "Private source map must cover exactly the input units")
    for unit_id, item in mappings.items():
        require(item.get("asset_id") in assets, "Unknown source asset in private map")
        start, end = item.get("in_ms"), item.get("out_ms")
        asset_duration = assets[item["asset_id"]].get("duration_ms")
        require(
            type(start) is int and type(end) is int and type(asset_duration) is int,
            "Source times and asset duration must be integer milliseconds",
        )
        require(0 <= start < end <= asset_duration, "Source range outside asset bounds")
        unit = lookup[unit_id]
        require(end - start == unit["end_ms"] - unit["start_ms"], "Private/virtual duration mismatch")

    timeline = []
    output_cursor = 0
    for run_index, run in enumerate(plan["sequence"]):
        for unit_id in run["unit_ids"]:
            item = mappings[unit_id]
            unit_duration = item["out_ms"] - item["in_ms"]
            previous = timeline[-1] if timeline else None
            if (
                previous
                and (modern or previous["run_index"] == run_index)
                and previous["asset_id"] == item["asset_id"]
                and previous["out_ms"] == item["in_ms"]
            ):
                previous["out_ms"] = item["out_ms"]
                previous["output_out_ms"] += unit_duration
                previous["unit_ids"].append(unit_id)
            else:
                timeline.append(
                    {
                        "run_index": run_index,
                        "unit_ids": [unit_id],
                        "asset_id": item["asset_id"],
                        "in_ms": item["in_ms"],
                        "out_ms": item["out_ms"],
                        "output_in_ms": output_cursor,
                        "output_out_ms": output_cursor + unit_duration,
                    }
                )
            output_cursor += unit_duration
    require(output_cursor == duration, "Resolved duration mismatch")
    # Source discontinuities can exist inside a virtual run. The LLM cannot see
    # the private map, so compile physical joins and flag these independently.
    resolved_joins = []
    for index, (left, right) in enumerate(zip(timeline, timeline[1:])):
        if not modern and left["run_index"] != right["run_index"]:
            decision = joins[left["run_index"]]
            resolved_joins.append(dict(decision, from_index=index, to_index=index + 1))
        else:
            note = (
                "Preview this connection between selected source ranges."
                if modern
                else "Private source mapping reveals a discontinuity inside a retained run; preview this connection."
            )
            review = join_review([left["unit_ids"][-1], right["unit_ids"][0]], note)
            resolved_joins.append(
                {
                    "from_index": index,
                    "to_index": index + 1,
                    "transition": "cut",
                    "review_required": True,
                    "note": review["note"],
                }
            )
    effective_status = "needs_review" if reviews else review_status
    return {
        "version": "2.0" if modern else "1.0",
        "input_id": analysis["input_id"],
        "status": effective_status,
        "render_allowed": effective_status == "ready",
        "duration_ms": duration,
        "removed_duration_ms": analysis["duration_ms"] - duration,
        "script": script,
        "timeline": timeline,
        "joins": resolved_joins,
        "review_items": reviews,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("plan", type=Path)
    parser.add_argument("source_map", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Validate everything before writing anything. Never overwrite input artifacts.
    require(
        args.output.resolve() not in {args.input.resolve(), args.plan.resolve(), args.source_map.resolve()},
        "Output must not overwrite an input file",
    )
    result = resolve(read_json(args.input), read_json(args.plan), read_json(args.source_map))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Valid plan: {result['duration_ms']} ms; status={result['status']}; "
        f"render_allowed={result['render_allowed']}; output={args.output}"
    )


if __name__ == "__main__":
    main()
