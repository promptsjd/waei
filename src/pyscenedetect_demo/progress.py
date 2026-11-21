"""Backend-owned progress descriptions; clients do not know pipeline internals."""

LABELS = {
    "detecting": "Detecting scenes",
    "exporting_frames": "Exporting frames",
    "extracting_audio": "Exporting audio",
    "describing": "Visual description",
    "transcribing": "Speech transcription",
    "writing_output": "Writing output",
}


class ProgressTracker:
    def __init__(self, stages):
        self.stages = tuple(stages)
        self.percent = 0

    def event(self, stage, current, total, message=""):
        if stage in self.stages:
            fraction = min(1, max(0, current / total)) if total else 0
            percent = 100 * (self.stages.index(stage) + fraction) / len(self.stages)
            self.percent = max(self.percent, min(99, round(percent)))
        return {
            "stage": stage,
            "current": current,
            "total": total,
            "message": message,
            "overall_percent": self.percent,
            "stage_label": LABELS.get(stage, stage.replace("_", " ").capitalize()),
        }
