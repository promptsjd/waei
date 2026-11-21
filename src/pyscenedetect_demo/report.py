from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def generate_html_report(*, analysis: dict[str, Any], output_path: Path) -> Path:
    output_path.write_text(_render_html(analysis), encoding="utf-8")
    return output_path


def generate_html_report_from_json(*, json_path: Path, output_path: Path | None = None) -> Path:
    analysis = json.loads(json_path.read_text(encoding="utf-8"))
    destination = output_path or json_path.with_name("report.html")
    return generate_html_report(analysis=analysis, output_path=destination)


def _render_html(analysis: dict[str, Any]) -> str:
    video = analysis["video"]
    summary = analysis["summary"]
    config = analysis["config"]
    scenes = analysis["scenes"]

    overview_items = [
        ("Video", video["name"]),
        ("Source file", video["path"]),
        ("Total duration", video.get("duration") or "-"),
        ("Frame rate", _format_number(video.get("fps"))),
        ("Scene count", str(summary["scene_count"])),
        ("Detector", config["detector"]),
        ("Threshold", _format_number(config["threshold"])),
        ("Minimum scene length", f'{_format_number(config["min_scene_len_seconds"])} s'),
        ("Transcription model", config["asr_model"] or "Disabled"),
        ("Transcription language", config["language"] or "auto"),
    ]

    overview_html = "".join(
        f"""
        <div class="metric">
          <div class="metric-label">{_escape(label)}</div>
          <div class="metric-value">{_escape(value)}</div>
        </div>
        """
        for label, value in overview_items
    )

    scene_cards = "".join(_render_scene_card(scene) for scene in scenes)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Storyboard · {_escape(video["name"])}</title>
  <style>
    :root {{
      --paper: #f4efe6;
      --panel: #fffdf8;
      --line: #d8cfbf;
      --line-strong: #baac94;
      --ink: #221f1b;
      --muted: #6f675c;
      --accent: #8e3f2b;
      --accent-soft: #f2e1d7;
      --header: #2f2922;
      --header-ink: #f7efe5;
      --shadow: 0 20px 48px rgba(55, 44, 28, 0.09);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(142, 63, 43, 0.08), transparent 30rem),
        linear-gradient(180deg, #f9f6f0 0%, var(--paper) 100%);
    }}

    .page {{
      width: min(1280px, calc(100vw - 28px));
      margin: 18px auto 60px;
    }}

    .hero {{
      background: linear-gradient(145deg, #2c261f 0%, #433224 100%);
      color: var(--header-ink);
      border-radius: 24px;
      padding: 28px 30px;
      box-shadow: var(--shadow);
    }}

    .eyebrow {{
      margin-bottom: 10px;
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: #d8c3ae;
    }}

    h1 {{
      margin: 0;
      font-size: 34px;
      line-height: 1.1;
    }}

    .subtitle {{
      max-width: 78ch;
      margin-top: 12px;
      color: #eadfd2;
      font-size: 15px;
      line-height: 1.6;
    }}

    .overview {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}

    .metric {{
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: rgba(255, 255, 255, 0.08);
    }}

    .metric-label {{
      margin-bottom: 8px;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #d8c5b2;
    }}

    .metric-value {{
      font-size: 14px;
      line-height: 1.45;
      word-break: break-word;
    }}

    .section-title {{
      margin: 28px 0 14px;
      font-size: 18px;
      color: var(--muted);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .scene-list {{
      display: grid;
      gap: 18px;
    }}

    .scene-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
      box-shadow: var(--shadow);
      break-inside: avoid;
      page-break-inside: avoid;
    }}

    .scene-header {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-bottom: 14px;
    }}

    .chip {{
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}

    .scene-layout {{
      display: grid;
      grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }}

    .thumb {{
      display: block;
      width: 100%;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #ddd6c8;
    }}

    .thumb-caption {{
      margin-top: 8px;
      font-size: 12px;
      line-height: 1.4;
      color: var(--muted);
      word-break: break-word;
    }}

    .sheet {{
      border: 1px solid var(--line-strong);
      border-radius: 16px;
      overflow: hidden;
      background: #fffefb;
    }}

    .sheet-row {{
      display: grid;
      grid-template-columns: 132px minmax(0, 1fr);
      border-top: 1px solid var(--line);
    }}

    .sheet-row:first-child {{
      border-top: 0;
    }}

    .sheet-label {{
      padding: 12px 12px 11px;
      background: #f3ebdf;
      border-right: 1px solid var(--line);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      color: var(--muted);
      text-transform: uppercase;
    }}

    .sheet-value {{
      padding: 12px 14px 11px;
      font-size: 15px;
      line-height: 1.6;
      min-height: 48px;
      white-space: pre-wrap;
      word-break: break-word;
    }}

    .double-row {{
      display: grid;
      grid-template-columns: 132px minmax(0, 1fr) 132px minmax(0, 1fr);
      border-top: 1px solid var(--line);
    }}

    .double-row .sheet-label:nth-child(3) {{
      border-left: 1px solid var(--line);
    }}

    .empty {{
      color: var(--muted);
      font-style: italic;
    }}

    footer {{
      margin-top: 28px;
      font-size: 12px;
      color: var(--muted);
      text-align: center;
    }}

    @media (max-width: 920px) {{
      .page {{
        width: min(100vw - 16px, 1280px);
        margin: 8px auto 26px;
      }}

      .hero {{
        border-radius: 18px;
        padding: 22px 18px;
      }}

      h1 {{
        font-size: 28px;
      }}

      .scene-layout {{
        grid-template-columns: 1fr;
      }}

      .sheet-row,
      .double-row {{
        grid-template-columns: 1fr;
      }}

      .sheet-label {{
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}

      .double-row .sheet-label:nth-child(3) {{
        border-left: 0;
      }}
    }}

    @media print {{
      @page {{
        size: A4;
        margin: 11mm;
      }}

      body {{
        background: #fff;
      }}

      .page {{
        width: auto;
        margin: 0;
      }}

      .hero,
      .scene-card {{
        box-shadow: none;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">Storyboard Script</div>
      <h1>{_escape(video["name"])}</h1>
      <div class="subtitle">
        Storyboard generated from scene detection, thumbnails and optional speech transcription.
        Open in a browser and print to PDF. Unsupported fields remain empty for manual review.
      </div>
      <div class="overview">{overview_html}</div>
    </section>

    <h2 class="section-title">Scene list</h2>
    <section class="scene-list">{scene_cards}</section>

    <footer>Generated from {_escape(summary["json_path"])}.</footer>
  </main>
</body>
</html>
"""


def _render_scene_card(scene: dict[str, Any]) -> str:
    return f"""
    <article class="scene-card">
      <div class="scene-header">
        <span class="chip">Scene {scene['scene_id']:03d}</span>
        <span class="chip">{_escape(scene['start_timecode'])} → {_escape(scene['end_timecode'])}</span>
        <span class="chip">{_format_number(scene['duration_seconds'])} s</span>
      </div>
      <div class="scene-layout">
        <div>
          <img class="thumb" src="{_escape(scene['screenshot_path'])}" alt="Scene {scene['scene_id']} frame">
          <div class="thumb-caption">{_escape(scene['screenshot_path'])}</div>
        </div>
        <div class="sheet">
          <div class="double-row">
            <div class="sheet-label">Start time</div>
            <div class="sheet-value">{_escape(scene['start_timecode'])}</div>
            <div class="sheet-label">End time</div>
            <div class="sheet-value">{_escape(scene['end_timecode'])}</div>
          </div>
          <div class="double-row">
            <div class="sheet-label">Duration</div>
            <div class="sheet-value">{_format_number(scene['duration_seconds'])} s</div>
            <div class="sheet-label">Representative frame</div>
            <div class="sheet-value">{scene['representative_frame']}</div>
          </div>
          <div class="double-row">
            <div class="sheet-label">Shot size</div>
            <div class="sheet-value">{_text_or_blank(scene.get('shot_size'))}</div>
            <div class="sheet-label">Camera motion</div>
            <div class="sheet-value">{_text_or_blank(scene.get('camera_motion'))}</div>
          </div>
          <div class="sheet-row">
            <div class="sheet-label">Visual description</div>
            <div class="sheet-value">{_text_or_blank(scene.get('visual_description'))}</div>
          </div>
          <div class="sheet-row">
            <div class="sheet-label">Dialogue</div>
            <div class="sheet-value">{_text_or_blank(scene.get('dialogue'))}</div>
          </div>
          <div class="double-row">
            <div class="sheet-label">Sound effects</div>
            <div class="sheet-value">{_text_or_blank(scene.get('sound_effects'))}</div>
            <div class="sheet-label">BGM</div>
            <div class="sheet-value">{_text_or_blank(scene.get('bgm'))}</div>
          </div>
          <div class="double-row">
            <div class="sheet-label">Audio clip</div>
            <div class="sheet-value">{_escape(scene['audio_path'])}</div>
            <div class="sheet-label">Transcription details</div>
            <div class="sheet-value">{_format_transcript_meta(scene)}</div>
          </div>
          <div class="sheet-row">
            <div class="sheet-label">Notes</div>
            <div class="sheet-value">{_text_or_blank(scene.get('notes'))}</div>
          </div>
        </div>
      </div>
    </article>
    """


def _format_transcript_meta(scene: dict[str, Any]) -> str:
    language = scene.get("transcript_language") or "-"
    confidence = scene.get("transcript_confidence")
    if confidence is None:
        confidence_text = "-"
    else:
        confidence_text = f"{confidence:.2f}"
    return _escape(f"language: {language} | confidence: {confidence_text}")


def _text_or_blank(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        return '<span class="empty"></span>'
    return _escape(text)


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _format_number(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)
