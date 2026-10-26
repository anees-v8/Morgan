"""
Stand-alone scene render worker:   python -m webreel.engine.video.render_worker <job.json> <result.json>

The producer launches one of these per scene so renders run in parallel without
multiprocessing's spawn semantics (which re-import the caller's __main__ and are hazardous for
any entry-point script lacking an `if __name__ == "__main__"` guard).
"""
import json
import sys
from pathlib import Path

_PATH_KEYS = ("image_path", "output_mp4", "live_clip", "watermark_path")
_TUPLE_KEYS = ("target_xy", "prev_cursor_norm", "target_size", "brand_rgb")


def run(job_file: str, result_file: str) -> None:
    import cv2
    cv2.setNumThreads(1)      # N workers x 4 OpenCV threads would just fight each other

    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    for k in _PATH_KEYS:
        if job.get(k):
            job[k] = Path(job[k])
    for k in _TUPLE_KEYS:
        if job.get(k) is not None:
            job[k] = tuple(job[k])

    from .effects import render_interactive_scene_frames
    out, click_time = render_interactive_scene_frames(**job)
    Path(result_file).write_text(json.dumps({"output": str(out), "click_time": float(click_time)}), encoding="utf-8")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
