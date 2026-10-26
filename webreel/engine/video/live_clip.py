"""
LiveClip: random access to a recorded browser beat (timestamped JPEG frames + exact pointer
track + click/URL/focus events written by engine.browser.live_capture).
"""
import json
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


class LiveClip:
    def __init__(self, meta_path):
        self.meta_path = Path(meta_path)
        meta: Dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.meta = meta
        self.dir = self.meta_path.parent
        self.scene_id: str = meta.get("scene_id", "")
        vp = meta["viewport"]
        self.size: Tuple[int, int] = (int(vp["width"]), int(vp["height"]))
        self.duration: float = float(meta["duration"])
        self.times = np.asarray(meta["frame_times"], dtype=np.float64)
        track = np.asarray(meta["cursor"]["track"], dtype=np.float64)
        self._tt, self._tx, self._ty = track[:, 0], track[:, 1], track[:, 2]
        self.cursor_start = tuple(meta["cursor"]["start"])
        self.cursor_end = tuple(meta["cursor"]["end"])
        self.clicks: List[Dict[str, Any]] = list(meta.get("clicks", []))
        self.focus: List[Dict[str, Any]] = list(meta.get("focus", []))
        self.phases: Dict[str, float] = dict(meta.get("phases", {}))
        self.url_events: List[Dict[str, Any]] = list(meta.get("url_events", []))
        self._cache: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._first_ok: Optional[np.ndarray] = None

    # ----------------------------------------------------------------- frames
    def frame_index(self, tau: float) -> int:
        i = int(np.searchsorted(self.times, tau, side="right")) - 1
        return max(0, min(len(self.times) - 1, i))

    def _decode(self, idx: int) -> np.ndarray:
        path = self.dir / f"{idx:05d}.jpg"
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Unreadable live frame: {path}")
        if (img.shape[1], img.shape[0]) != self.size:
            img = cv2.resize(img, self.size, interpolation=cv2.INTER_AREA)
        return img

    def frame_at(self, tau: float) -> np.ndarray:
        """Sample-and-hold: the frame that was on screen at clip time tau."""
        idx = self.frame_index(tau)
        img = self._cache.get(idx)
        if img is None:
            img = self._decode(idx)
            self._cache[idx] = img
            if len(self._cache) > 10:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(idx)
        return img

    # ---------------------------------------------------------------- pointer
    def cursor_at(self, tau: float) -> Tuple[float, float]:
        return float(np.interp(tau, self._tt, self._tx)), float(np.interp(tau, self._tt, self._ty))

    def end_cursor_norm(self) -> Tuple[float, float]:
        return self.cursor_end[0] / self.size[0], self.cursor_end[1] / self.size[1]

    # ---------------------------------------------------------------- cleanup
    def cleanup(self):
        """Frames are bulky (~150KB each); drop the JPEGs once rendered, keep the tiny clip.json."""
        self._cache.clear()
        for jpg in self.dir.glob("*.jpg"):
            try:
                jpg.unlink()
            except OSError:
                pass
