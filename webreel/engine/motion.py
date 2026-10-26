"""
Pure-math motion primitives shared by the browser capture (real mouse choreography)
and the video renderer (camera, cursor, UI animation). No I/O, no heavy imports.

Everything here is deterministic given a seed so a captured cursor path can be
re-evaluated at any time stamp by the renderer.
"""
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

Vec = Tuple[float, float]


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------
def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def smootherstep(t: float) -> float:
    t = clamp(t)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def min_jerk(t: float) -> float:
    """Minimum-jerk position profile: the classic model of a human reaching movement."""
    t = clamp(t)
    return 10.0 * t ** 3 - 15.0 * t ** 4 + 6.0 * t ** 5


def ease_out_cubic(t: float) -> float:
    t = clamp(t)
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    t = clamp(t)
    return 4.0 * t ** 3 if t < 0.5 else 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def ease_out_expo(t: float) -> float:
    t = clamp(t)
    return 1.0 if t >= 1.0 else 1.0 - 2.0 ** (-10.0 * t)


def ease_out_back(t: float, overshoot: float = 1.35) -> float:
    t = clamp(t)
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Critically damped spring (exact integration, frame-rate independent)
# ---------------------------------------------------------------------------
def spring_step(x, v, target, omega: float, dt: float):
    """
    Advance a critically damped spring by dt seconds using the closed-form solution.
    Works on scalars or numpy arrays. Retargeting mid-flight keeps velocity continuous,
    which is what makes camera moves feel physical instead of keyframed.
    """
    d = x - target
    e = math.exp(-omega * dt)
    tmp = (v + omega * d) * dt
    new_x = target + (d + tmp) * e
    new_v = (v - omega * tmp) * e
    return new_x, new_v


# ---------------------------------------------------------------------------
# Human-like cursor movement
# ---------------------------------------------------------------------------
def fitts_duration(distance: float, target_width: float = 48.0, slow: float = 1.0) -> float:
    """
    Fitts's law, tuned for *demo pacing*: deliberately ~35% slower than a real user
    so viewers can follow the pointer. slow>1 makes it slower still.
    """
    index_of_difficulty = math.log2(1.0 + distance / max(target_width, 12.0))
    t = 0.52 + 0.30 * index_of_difficulty
    return clamp(t * 1.15 * slow, 0.55, 2.1)


class CursorMove:
    """
    One pointing gesture from p0 to p1: a gently curved cubic Bezier travelled with a
    minimum-jerk speed profile, with an optional small overshoot-and-correct at the end
    (the signature of a real hand). Evaluate with pos(t) for t in seconds since start.
    """

    def __init__(
        self,
        p0: Vec,
        p1: Vec,
        duration: Optional[float] = None,
        target_width: float = 48.0,
        seed: int = 0,
        slow: float = 1.0,
        overshoot: bool = True,
    ):
        rng = random.Random(seed)
        self.p0 = (float(p0[0]), float(p0[1]))
        self.p1 = (float(p1[0]), float(p1[1]))
        dx, dy = self.p1[0] - self.p0[0], self.p1[1] - self.p0[1]
        self.dist = math.hypot(dx, dy)
        self.duration = float(duration) if duration else (
            fitts_duration(self.dist, target_width, slow) if self.dist > 4 else 0.25
        )

        if self.dist < 1e-6:
            ux, uy = 1.0, 0.0
        else:
            ux, uy = dx / self.dist, dy / self.dist
        nx, ny = -uy, ux
        side = rng.choice((-1.0, 1.0))

        # Overshoot only on long, ballistic moves, and only along the travel direction.
        self.settle_frac = 0.0
        self.end_main = self.p1
        if overshoot and self.dist > 220 and rng.random() < 0.65:
            o = min(10.0, 0.022 * self.dist) * rng.uniform(0.6, 1.0)
            self.end_main = (self.p1[0] + ux * o, self.p1[1] + uy * o)
            self.settle_frac = 0.17

        D = self.dist
        k1 = rng.uniform(0.035, 0.10) * D * side
        k2 = rng.uniform(0.015, 0.06) * D * side
        a, b = self.p0, self.end_main
        self.c1 = (a[0] + (b[0] - a[0]) * 0.28 + nx * k1, a[1] + (b[1] - a[1]) * 0.28 + ny * k1)
        self.c2 = (a[0] + (b[0] - a[0]) * 0.74 + nx * k2, a[1] + (b[1] - a[1]) * 0.74 + ny * k2)

    def _bezier(self, s: float) -> Vec:
        a, c1, c2, b = self.p0, self.c1, self.c2, self.end_main
        u = 1.0 - s
        x = u ** 3 * a[0] + 3 * u * u * s * c1[0] + 3 * u * s * s * c2[0] + s ** 3 * b[0]
        y = u ** 3 * a[1] + 3 * u * u * s * c1[1] + 3 * u * s * s * c2[1] + s ** 3 * b[1]
        return x, y

    def pos(self, t: float) -> Vec:
        if self.duration <= 0:
            return self.p1
        tau = clamp(t / self.duration)
        main_end = 1.0 - self.settle_frac
        if tau <= main_end:
            # Slightly front-loaded: the ballistic phase is quicker than the homing phase.
            s = min_jerk((tau / main_end) ** 0.93)
            return self._bezier(s)
        k = smoothstep((tau - main_end) / max(self.settle_frac, 1e-6))
        return (
            self.end_main[0] + (self.p1[0] - self.end_main[0]) * k,
            self.end_main[1] + (self.p1[1] - self.end_main[1]) * k,
        )


def idle_drift(t: float, seed: int = 0, amplitude: float = 1.1) -> Vec:
    """Tiny low-frequency hand tremor so a resting cursor never looks frozen."""
    rng = random.Random(seed)
    p = [rng.uniform(0, math.tau) for _ in range(4)]
    x = amplitude * (0.8 * math.sin(math.tau * 0.31 * t + p[0]) + 0.35 * math.sin(math.tau * 0.83 * t + p[1]))
    y = amplitude * (0.8 * math.sin(math.tau * 0.27 * t + p[2]) + 0.35 * math.sin(math.tau * 0.71 * t + p[3]))
    return x, y


@dataclass
class CursorSegment:
    """A timed pointing gesture inside a clip (times are seconds since clip start)."""
    t0: float
    move: CursorMove

    @property
    def t1(self) -> float:
        return self.t0 + self.move.duration


def evaluate_track(segments: List[CursorSegment], start_pos: Vec, t: float) -> Vec:
    """Cursor position at time t given an ordered list of gestures; rests between them."""
    pos = start_pos
    for seg in segments:
        if t < seg.t0:
            return pos
        if t <= seg.t1:
            return seg.move.pos(t - seg.t0)
        pos = seg.move.p1
    return pos


def sample_track(segments: List[CursorSegment], start_pos: Vec, duration: float, hz: int = 120) -> List[List[float]]:
    """Dense [t, x, y] samples (JSON friendly) of the whole track."""
    n = int(duration * hz) + 1
    out = []
    for i in range(n):
        t = i / hz
        x, y = evaluate_track(segments, start_pos, t)
        out.append([round(t, 4), round(x, 2), round(y, 2)])
    return out


def sample_dense(track: List[List[float]], t: float) -> Vec:
    """Linear interpolation inside a dense [t,x,y] track."""
    if not track:
        return (0.0, 0.0)
    ts = [p[0] for p in track]
    if t <= ts[0]:
        return (track[0][1], track[0][2])
    if t >= ts[-1]:
        return (track[-1][1], track[-1][2])
    arr = np.asarray(track, dtype=np.float64)
    return (float(np.interp(t, arr[:, 0], arr[:, 1])), float(np.interp(t, arr[:, 0], arr[:, 2])))
