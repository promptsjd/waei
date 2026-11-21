from __future__ import annotations

import html
import json
import warnings
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from pyscenedetect_demo.detection import detect_boundaries
from pyscenedetect_demo.media import extract_frame as _extract_frame

@dataclass(slots=True)
class ShotRecord:
    shot_id: int
    start_frame: int
    end_frame: int
    start_timecode: str
    end_timecode: str
    start_frame_path: str
    end_frame_path: str


def run_shotlist(
    *,
    video_path: Path,
    output_root: Path,
    detector_name: str,
    threshold: float,
    min_scene_len_seconds: float,
    show_progress: bool,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> dict[str, Any]:
    video, fps, _, scene_list = detect_boundaries(video_path=video_path,
        detector_name=detector_name, threshold=threshold,
        min_scene_len_seconds=min_scene_len_seconds, show_progress=show_progress,
        progress_callback=progress_callback)

    output_dir = output_root / video_path.stem / "shotlist"
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    shots = _export_shot_frames(
        scene_list=scene_list,
        frames_dir=frames_dir,
        video_path=video_path,
        fps=fps,
        progress_callback=progress_callback,
    )

    if progress_callback:
        progress_callback("writing_output", 1, 1, "Generating HTML & PDF")

    html_path = output_dir / "shotlist.html"
    _generate_html(shots=shots, video_name=video_path.name, output_path=html_path)

    pdf_path = output_dir / "shotlist.pdf"
    # WeasyPrint's native libraries are optional, especially on Windows.
    try:
        import weasyprint
        weasyprint.HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    except (ImportError, OSError) as exc:
        warnings.warn(f"Automatic PDF export unavailable ({exc}). Open shotlist.html and print to PDF.")
        pdf_path = None

    json_path = output_dir / "shots.json"
    result = {
        "video": {
            "path": str(video_path.resolve()),
            "name": video_path.name,
            "fps": fps,
            "duration": video.duration.get_timecode() if video.duration is not None else None,
        },
        "config": {
            "detector": detector_name,
            "threshold": threshold,
            "min_scene_len_seconds": min_scene_len_seconds,
        },
        "summary": {
            "shot_count": len(shots),
            "output_dir": str(output_dir.resolve()),
            "frames_dir": str(frames_dir.resolve()),
            "html_path": str(html_path.resolve()),
            "pdf_path": str(pdf_path.resolve()) if pdf_path else None,
            "json_path": str(json_path.resolve()),
        },
        "shots": [asdict(shot) for shot in shots],
    }
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _export_shot_frames(
    *,
    scene_list: list[tuple[Any, Any]],
    frames_dir: Path,
    video_path: Path,
    fps: float,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> list[ShotRecord]:
    total = len(scene_list)
    shots: list[ShotRecord] = []
    for index, (start, end) in enumerate(scene_list, start=1):
        if progress_callback:
            progress_callback("exporting_frames", index, total, f"Shot {index}/{total}")
        start_frame = int(start.get_frames())
        last_frame = max(start_frame, int(end.get_frames()) - 1)

        start_path = frames_dir / f"shot_{index:04d}_start.jpg"
        end_path = frames_dir / f"shot_{index:04d}_end.jpg"

        _extract_frame(video_path=video_path, frame_number=start_frame, fps=fps, destination=start_path)
        _extract_frame(video_path=video_path, frame_number=last_frame, fps=fps, destination=end_path)

        shots.append(
            ShotRecord(
                shot_id=index,
                start_frame=start_frame,
                end_frame=last_frame,
                start_timecode=start.get_timecode(),
                end_timecode=end.get_timecode(),
                start_frame_path=str(start_path.relative_to(frames_dir.parent)),
                end_frame_path=str(end_path.relative_to(frames_dir.parent)),
            )
        )
    return shots


def _generate_html(*, shots: list[ShotRecord], video_name: str, output_path: Path) -> Path:
    rows = "".join(_render_shot_row(shot) for shot in shots)
    html_content = _HTML_TEMPLATE.format(
        video_name=_esc(video_name),
        shot_count=len(shots),
        rows=rows,
    )
    output_path.write_text(html_content, encoding="utf-8")
    return output_path


def _render_shot_row(shot: ShotRecord) -> str:
    return f"""
        <tr>
          <td class="shot-num">{shot.shot_id}</td>
          <td class="frame-cell">
            <img src="{_esc(shot.start_frame_path)}" alt="Shot {shot.shot_id} start">
            <div class="frame-tc">{_esc(shot.start_timecode)}</div>
          </td>
          <td class="frame-cell">
            <img src="{_esc(shot.end_frame_path)}" alt="Shot {shot.shot_id} end">
            <div class="frame-tc">{_esc(shot.end_timecode)}</div>
          </td>
        </tr>
        """


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Shot list · {video_name}</title>
  <style>
    :root {{
      --paper: #f4efe6;
      --panel: #fffdf8;
      --line: #d8cfbf;
      --ink: #221f1b;
      --muted: #6f675c;
      --accent: #8e3f2b;
      --accent-soft: #f2e1d7;
      --header: #2f2922;
      --header-ink: #f7efe5;
      --shadow: 0 2px 12px rgba(55, 44, 28, 0.06);
    }}

    * {{ box-sizing: border-box; }}

    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
      background: var(--paper);
    }}

    .page {{
      width: min(1400px, calc(100vw - 28px));
      margin: 18px auto 60px;
    }}

    .hero {{
      background: linear-gradient(145deg, #2c261f 0%, #433224 100%);
      color: var(--header-ink);
      border-radius: 20px;
      padding: 22px 28px;
      box-shadow: 0 12px 32px rgba(55, 44, 28, 0.12);
      margin-bottom: 24px;
    }}

    h1 {{
      margin: 0;
      font-size: 26px;
    }}

    .hero-meta {{
      margin-top: 8px;
      font-size: 14px;
      color: #d8c5b2;
    }}

    .shot-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
    }}

    .shot-table th {{
      position: sticky;
      top: 0;
      background: var(--header);
      color: var(--header-ink);
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 12px 16px;
      text-align: center;
      z-index: 1;
    }}

    .shot-table th:first-child {{
      border-radius: 12px 0 0 0;
      width: 60px;
    }}

    .shot-table th:last-child {{
      border-radius: 0 12px 0 0;
    }}

    .shot-table td {{
      padding: 10px 12px;
      vertical-align: top;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}

    .shot-table tr:last-child td:first-child {{
      border-radius: 0 0 0 12px;
    }}

    .shot-table tr:last-child td:last-child {{
      border-radius: 0 0 12px 0;
    }}

    .shot-num {{
      text-align: center;
      font-size: 14px;
      font-weight: 700;
      color: var(--accent);
      min-width: 40px;
    }}

    .frame-cell {{
      text-align: center;
    }}

    .frame-cell img {{
      display: block;
      width: 100%;
      max-width: 480px;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      border-radius: 10px;
      border: 1px solid var(--line);
      background: #ddd6c8;
      margin: 0 auto;
    }}

    .frame-tc {{
      margin-top: 6px;
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.04em;
    }}

    footer {{
      margin-top: 24px;
      font-size: 12px;
      color: var(--muted);
      text-align: center;
    }}

    @media (max-width: 760px) {{
      .page {{
        width: min(100vw - 12px, 1400px);
        margin: 6px auto 20px;
      }}

      .shot-table th,
      .shot-table td {{
        padding: 6px;
      }}

      .frame-cell img {{
        max-width: 100%;
      }}
    }}

    @media print {{
      @page {{
        size: A4 landscape;
        margin: 8mm;
      }}

      body {{
        background: #fff;
      }}

      .hero {{
        box-shadow: none;
        background: #2f2922;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}

      .shot-table th {{
        background: #2f2922;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}

      .frame-cell img {{
        max-width: 320px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Shot list · {video_name}</h1>
      <div class="hero-meta">Total: {shot_count} Scene</div>
    </section>

    <table class="shot-table">
      <thead>
        <tr>
          <th>#</th>
          <th>Start frame</th>
          <th>End frame</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>

    <footer>Shot list for {video_name}</footer>
  </main>
</body>
</html>
"""


def regenerate_shotlist(*, json_path):
    """Public report operation; web callers do not reconstruct internal records."""
    from pyscenedetect_demo.storage import read_json
    json_path = Path(json_path)
    data = read_json(json_path)
    shots = [ShotRecord(**{key: item[key] for key in ShotRecord.__dataclass_fields__})
             for item in data["shots"]]
    return _generate_html(shots=shots, video_name=data["video"]["name"],
                          output_path=json_path.parent / "shotlist.html")
