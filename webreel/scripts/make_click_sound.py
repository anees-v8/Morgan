"""
Synthesises the mouse-click foley used by the audio mixer (engine/audio/music/mouse_click.wav).

A real mouse click is TWO events: the button going down (the loud one) and coming back up
(~90 ms later, softer and a little higher). Each event is three layers:

  - a very short broadband "tick"  (the contact transient, band-passed noise, ~2 ms)
  - a damped plastic resonance     (the switch body, ~1.4 kHz + overtone, ~10 ms)
  - a low "thock"                  (the housing, ~170 Hz with a small pitch drop, ~25 ms)

Gentle low-pass, soft attack, peak at -4 dBFS. The file is 44.1 kHz stereo; the down-click sits at
t=0 and the up-click at t=PRESS_MS, matching the visual press length in the renderer (0.095 s).

    python webreel/scripts/make_click_sound.py [--out path] [--press-ms 95] [--seed 7]
"""
import argparse
import wave
from pathlib import Path

import numpy as np

SR = 44100


def _bandpass(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    mask = np.clip((f - lo) / (lo * 0.4), 0, 1) * np.clip((hi - f) / (hi * 0.3), 0, 1)
    return np.fft.irfft(spec * mask, len(x))


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    return np.fft.irfft(spec * np.clip((cutoff * 1.25 - f) / (cutoff * 0.5), 0, 1), len(x))


def hit(pitch: float, tick: float, body: float, thock: float, seed: int, length_ms: float = 90.0) -> np.ndarray:
    n = int(length_ms / 1000.0 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    tick_sig = _bandpass(rng.standard_normal(n), 1800 * pitch, 7500 * pitch) * np.exp(-t / 0.0022)
    body_sig = (0.75 * np.sin(2 * np.pi * 1380 * pitch * t) * np.exp(-t / 0.010)
                + 0.30 * np.sin(2 * np.pi * 2870 * pitch * t + 0.7) * np.exp(-t / 0.0055))
    f_inst = 165 * pitch + 70 * pitch * np.exp(-t / 0.012)                    # housing "thock" with a small pitch drop
    phase = 2 * np.pi * np.cumsum(f_inst) / SR
    thock_sig = np.sin(phase) * np.exp(-t / 0.022)
    sig = tick * tick_sig * 1.4 + body * body_sig + thock * thock_sig
    sig *= np.minimum(1.0, t / 0.0004)                                         # 0.4 ms soft attack: no digital "pop"
    return sig / (np.abs(sig).max() + 1e-9)


def build(press_ms: float = 95.0, seed: int = 7) -> np.ndarray:
    total = int((press_ms + 130.0) / 1000.0 * SR)
    out = np.zeros(total)
    down = hit(pitch=1.0, tick=0.9, body=0.8, thock=0.75, seed=seed)
    up = hit(pitch=1.16, tick=0.8, body=0.7, thock=0.35, seed=seed + 1, length_ms=70.0) * 0.50
    out[:len(down)] += down
    s = int(press_ms / 1000.0 * SR)
    out[s:s + len(up)] += up
    out = _lowpass(out, 9500.0)
    # 30 ms tail fade so nothing is cut abruptly
    fade = int(0.03 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)
    out *= 10 ** (-4.0 / 20.0) / (np.abs(out).max() + 1e-9)                    # peak -4 dBFS
    return out


def write_wav(path: Path, mono: np.ndarray) -> None:
    # tiny inter-channel delay (0.15 ms) gives the click a little air without sounding "wide"
    d = int(0.00015 * SR)
    left = mono
    right = np.concatenate([np.zeros(d), mono[:-d]]) if d else mono
    pcm = (np.stack([left, right], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "engine" / "audio" / "music" / "mouse_click.wav"))
    ap.add_argument("--press-ms", type=float, default=95.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    sig = build(a.press_ms, a.seed)
    write_wav(Path(a.out), sig)
    spec = np.abs(np.fft.rfft(sig * np.hanning(len(sig))))
    f = np.fft.rfftfreq(len(sig), 1 / SR)
    print(f"wrote {a.out}: {len(sig) / SR * 1000:.0f} ms, peak {20 * np.log10(np.abs(sig).max()):.1f} dBFS, "
          f"spectral centroid {(spec * f).sum() / spec.sum():.0f} Hz")
