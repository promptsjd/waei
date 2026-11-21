"""Conservative sentence-sized selections from timed words."""

import re

from pyscenedetect_demo.settings import SegmentationPolicy

SEGMENTATION_VERSION = 2


def ends_sentence(text):
    text = text.rstrip().rstrip('\"\'”’»)]}')
    # ASR punctuation is only a candidate boundary, but commas, semicolons,
    # fillers, pauses and arbitrary size limits are never complete sentences.
    if text.endswith(("...", "…")) or re.search(
        r"\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e)\.$", text, re.IGNORECASE
    ):
        return False
    return text.endswith((".", "!", "?", "۔", "؟", "।", "。", "！", "？"))


def build_units(words, duration_ms, *, unknown_speech=False, policy=None):
    """Keep sentences intact, including hesitation and pauses within them.

    Without sentence punctuation, retain the entire passage as one unit rather
    than creating independently removable fragments of an unfinished thought.
    """
    policy = policy or SegmentationPolicy()
    clean = []
    previous_end = 0
    for word in words:
        start = max(previous_end, min(duration_ms, round(float(word["start"]) * 1000)))
        end = min(duration_ms, max(start + 1, round(float(word["end"]) * 1000)))
        if start >= end or not word["word"].strip():
            continue
        clean.append({**word, "start_ms": start, "end_ms": end})
        previous_end = end
    if not clean:
        return [
            {
                "start_ms": 0,
                "end_ms": duration_ms,
                "kind": "speech" if unknown_speech else "silence",
                "text": "",
                "speaker": None,
                "speech_confidence": None,
                "boundary_quality": "uncertain" if unknown_speech else "candidate",
            }
        ]
    groups, current = [], []
    for word in clean:
        current.append(word)
        if ends_sentence(word["word"]):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    speech = []
    for group in groups:
        probabilities = [item["probability"] for item in group if item.get("probability") is not None]
        speech.append(
            {
                "start_ms": max(0, group[0]["start_ms"] - policy.leading_padding_ms),
                "end_ms": min(duration_ms, group[-1]["end_ms"] + policy.trailing_padding_ms),
                "kind": "speech",
                "text": " ".join(item["word"].strip() for item in group),
                "speaker": None,
                "speech_confidence": round(sum(probabilities) / len(probabilities), 4)
                if probabilities
                else None,
                "boundary_quality": "candidate",
            }
        )
    for index, (left, right) in enumerate(zip(speech, speech[1:])):
        if left["end_ms"] > right["start_ms"]:
            # Divide padding at the actual word boundary, rather than between
            # padded estimates (which can collapse very short consecutive units).
            boundary = (groups[index][-1]["end_ms"] + groups[index + 1][0]["start_ms"]) // 2
            left["end_ms"] = boundary
            right["start_ms"] = boundary
    result, cursor = [], 0
    for item in speech:
        if item["start_ms"] > cursor:
            if item["start_ms"] - cursor >= policy.silence_ms:
                result.append(
                    {
                        "start_ms": cursor,
                        "end_ms": item["start_ms"],
                        "kind": "silence",
                        "text": "",
                        "speaker": None,
                        "speech_confidence": None,
                        "boundary_quality": "candidate",
                    }
                )
            elif result:
                result[-1]["end_ms"] = item["start_ms"]
            else:
                item["start_ms"] = cursor
        if item["end_ms"] - item["start_ms"] < policy.uncertain_ms:
            item["boundary_quality"] = "uncertain"
        result.append(item)
        cursor = item["end_ms"]
    if cursor < duration_ms:
        if duration_ms - cursor >= policy.silence_ms:
            result.append(
                {
                    "start_ms": cursor,
                    "end_ms": duration_ms,
                    "kind": "silence",
                    "text": "",
                    "speaker": None,
                    "speech_confidence": None,
                    "boundary_quality": "candidate",
                }
            )
        else:
            result[-1]["end_ms"] = duration_ms
    return result
