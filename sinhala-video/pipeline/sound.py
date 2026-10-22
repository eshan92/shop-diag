"""Synthesized background music and scene-synced sound effects (numpy only).

Music styles:
  suspense - cinematic documentary bed: sub drone, slow minor string pad
             (Dm - Bb - Gm - A), heartbeat pulse, high shimmer, riser into the
             last scene
  ambient  - the plain dark drone

Sound effects (added on top of any music, never ducked):
  whoosh   - on every scene transition (panned with wipe direction)
  impact   - deep hit on the first frame and when the last scene lands
"""
from __future__ import annotations

import re

import numpy as np

from .audio_io import SR

TAU = 2 * np.pi


def style_for(mood: str | None, default: str = "suspense") -> str:
    m = (mood or "").lower()
    if not m:
        return default
    if re.search(r"ambient|calm|soft|chill|relax|minimal", m) and \
            not re.search(r"suspens|tension|thrill|dramatic|cinematic|documentary|dark|mystery", m):
        return "ambient"
    return "suspense"


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Zero-phase band-pass via FFT with soft (raised-cosine) edges. x: (n,) or (n, ch)."""
    n = len(x)
    m = 1 << (n - 1).bit_length()  # pad to a power of two: odd lengths make the FFT very slow
    f = np.fft.rfftfreq(m, 1 / SR)
    mask = np.ones_like(f)
    if lo > 0:
        w = lo * 0.5
        mask *= np.clip((f - (lo - w)) / w, 0, 1)
    if hi < SR / 2:
        w = hi * 0.5
        mask *= np.clip(((hi + w) - f) / w, 0, 1)
    mask = 0.5 - 0.5 * np.cos(np.pi * mask)
    X = np.fft.rfft(x, n=m, axis=0)
    return np.fft.irfft(X * (mask[:, None] if x.ndim == 2 else mask), n=m, axis=0)[:n]


def _norm(x):
    return x / (np.max(np.abs(x)) + 1e-9)


# ------------------------------------------------------------------ music

def drone(total: float, seed: int = 7) -> np.ndarray:
    """Dark ambient bed: detuned low pad + slow filtered rumble, stereo."""
    n = int(total * SR) + 1
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    out = np.zeros((n, 2))
    for f, a in ((36.71, 1.0), (55.0, 0.55), (73.42, 0.6), (87.31, 0.25), (110.0, 0.18)):
        for ch, det in ((0, 0.998), (1, 1.002)):
            lfo = 0.65 + 0.35 * np.sin(TAU * (0.05 + 0.02 * a) * t + rng.uniform(0, TAU))
            out[:, ch] += a * lfo * np.sin(TAU * f * det * t + rng.uniform(0, TAU))
    rumble = _norm(_band(rng.standard_normal((n, 2)), 20, 180))
    out += 0.6 * rumble * (0.5 + 0.5 * np.sin(TAU * 0.03 * t))[:, None]
    return _norm(out)


def _pad_voice(freq, t, rng, harmonics=10, sr=SR):
    """Soft string-like tone: band-limited saw (1/k harmonics), two detuned voices, vibrato."""
    out = np.zeros((len(t), 2))
    vib = 0.0025 * np.sin(TAU * 4.8 * t + rng.uniform(0, TAU))
    warped = t + np.cumsum(vib) / sr          # time axis of a slightly wobbling oscillator
    for ch, det in ((0, 0.9965), (1, 1.0035)):
        base = TAU * freq * det * warped
        for k in range(1, harmonics + 1):
            if freq * k > min(5000, sr / 2.2):
                break
            out[:, ch] += (1 / k) * np.exp(-k / 6) * np.sin(k * base + rng.uniform(0, TAU))
    return out


def suspense_bed(total: float, scenes: list[dict], seed: int = 11) -> np.ndarray:
    n = int(total * SR) + 1
    t = np.arange(n) / SR
    rng = np.random.default_rng(seed)
    out = 0.55 * drone(total, seed)

    # slow minor progression, 8 s per chord, 2 s crossfades
    chords = [(146.83, 174.61, 220.00),    # Dm
              (116.54, 146.83, 174.61),    # Bb
              (98.00, 116.54, 146.83),     # Gm
              (110.00, 138.59, 164.81)]    # A (dominant -> tension)
    seg, xf = 8.0, 2.0
    # the pad is band-limited to 2.6 kHz, so build it at 12 kHz and upsample (4x faster)
    lsr = 12000
    n_lo = int(total * lsr) + 1
    t_lo = np.arange(n_lo) / lsr
    pad_lo = np.zeros((n_lo, 2))
    for c in range(int(np.ceil(total / seg)) + 1):
        s0 = c * seg - xf / 2
        a, b = max(0, int(s0 * lsr)), min(n_lo, int((s0 + seg + xf) * lsr))
        if a >= b:
            continue
        tt = t_lo[a:b]
        env = np.clip((tt - s0) / xf, 0, 1) * np.clip((s0 + seg + xf - tt) / xf, 0, 1)
        env = (0.5 - 0.5 * np.cos(np.pi * env))[:, None]
        for f in chords[c % len(chords)]:
            pad_lo[a:b] += env * _pad_voice(f, tt, rng, sr=lsr)
    pad = np.stack([np.interp(t, t_lo, pad_lo[:, ch]) for ch in (0, 1)], axis=1)
    pad = _band(pad, 90, 2600)
    swell = 0.75 + 0.25 * np.sin(TAU * t / 16 - np.pi / 2)
    out += 0.55 * _norm(pad) * swell[:, None]

    # heartbeat: "lub-dub" low thumps at 62 bpm after the intro
    beat = np.zeros(n)
    period = 60 / 62
    for k in range(int(total / period) + 1):
        for off, amp in ((0.0, 1.0), (0.22, 0.6)):
            s = 2.0 + k * period + off
            a = int(s * SR)
            if a >= n - 10 or s > total - 2.5:
                continue
            ln = min(int(0.35 * SR), n - a)
            tt = np.arange(ln) / SR
            fr = 38 + 30 * np.exp(-tt * 30)                 # quick pitch drop
            beat[a:a + ln] += amp * np.sin(TAU * np.cumsum(fr) / SR) * np.exp(-tt * 11)
    beat *= np.clip((t - 2.0) / 4.0, 0, 1)                   # fade the pulse in
    out += 0.5 * beat[:, None]

    # high shimmer (tremolo fifth), very quiet
    shim = sum(np.sin(TAU * f * t + p) for f, p in ((880.0, 0.0), (1318.5, 1.3), (1760.0, 2.1)))
    shim *= 0.5 + 0.5 * np.sin(TAU * 0.11 * t)
    out[:, 0] += 0.035 * shim * (0.6 + 0.4 * np.sin(TAU * 0.07 * t))
    out[:, 1] += 0.035 * shim * (0.6 + 0.4 * np.cos(TAU * 0.07 * t))

    # riser into the last scene
    if len(scenes) > 1:
        end = scenes[-1]["start"]
        a = max(0, int((end - 3.0) * SR))
        b = min(n, int(end * SR))
        if b > a:
            tt = (np.arange(b - a) / SR)
            k = tt / max(tt[-1], 1e-6)
            noise = _band(rng.standard_normal((b - a, 2)), 800, 9000)
            tone = np.sin(TAU * np.cumsum(220 + 660 * k ** 2) / SR)
            out[a:b] += (0.25 * _norm(noise) + 0.15 * tone[:, None]) * (k ** 2)[:, None]
    return _norm(out)


def synth_music(style: str, total: float, scenes: list[dict]) -> np.ndarray:
    if style == "ambient":
        return drone(total).astype(np.float32)
    return suspense_bed(total, scenes).astype(np.float32)


# -------------------------------------------------------------------- sfx

def whoosh(rng, dur=0.9, direction=1) -> np.ndarray:
    ln = int(dur * SR)
    tt = np.arange(ln) / SR
    k = tt / dur
    env = np.where(k < 0.55, (k / 0.55) ** 2, np.exp(-(k - 0.55) * 9))
    # two bands: airy top + body, body rises in level towards the peak
    air = _norm(_band(rng.standard_normal(ln), 1500, 9000))
    body = _norm(_band(rng.standard_normal(ln), 250, 1500))
    mono = env * (0.6 * air + 0.8 * body * np.clip(k * 2, 0, 1))
    pan = np.clip(0.5 + direction * (k - 0.5) * 1.2, 0, 1)      # sweep across
    return np.stack([mono * np.cos(pan * np.pi / 2), mono * np.sin(pan * np.pi / 2)], axis=1)


def impact(rng, dur=2.5) -> np.ndarray:
    ln = int(dur * SR)
    tt = np.arange(ln) / SR
    fr = 30 + 45 * np.exp(-tt * 9)
    boom = np.sin(TAU * np.cumsum(fr) / SR) * np.exp(-tt * 2.2)
    crack = _norm(_band(rng.standard_normal(ln), 300, 6000)) * np.exp(-tt * 40)
    tail = _band(rng.standard_normal((ln, 2)), 60, 900)
    tail = _norm(tail) * (np.exp(-tt * 2.8) * np.clip(tt / 0.03, 0, 1))[:, None]
    mono = boom + 0.35 * crack
    return mono[:, None] * np.ones((1, 2)) + 0.25 * tail


def sfx_track(scenes: list[dict], total: float, transition: float, seed: int = 5) -> np.ndarray:
    n = int(total * SR) + 1
    out = np.zeros((n, 2))
    rng = np.random.default_rng(seed)

    def place(x, at, gain):
        a = int(at * SR)
        if a < 0:
            x, a = x[-a:], 0
        b = min(n, a + len(x))
        if b > a:
            out[a:b] += gain * x[:b - a]

    place(impact(rng), 0.02, 1.0)
    for i, sc in enumerate(scenes[1:], 1):
        kind = sc.get("transition", "fade")
        d = 0.9 if kind != "fade" else 0.7
        # whoosh peaks a little after the cut, in the middle of the transition
        place(whoosh(rng, d, direction=-1 if kind == "wipe" else 1), sc["start"] - 0.55 * d + transition / 2,
              0.8 if kind != "fade" else 0.45)
    if len(scenes) > 1:
        place(impact(rng), scenes[-1]["start"], 0.8)
    return out.astype(np.float32)
