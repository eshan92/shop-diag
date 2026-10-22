"""Audio: voice track, music bed (file or synthesized), sound effects, ducking, loudness."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .audio_io import SR, read_audio, write_wav
from .sound import sfx_track, style_for, synth_music


def voice_track(scenes: list[dict], speeches: list, total: float) -> np.ndarray:
    out = np.zeros((int(total * SR) + 1, 1), dtype=np.float32)
    for sc, sp in zip(scenes, speeches):
        if sp is None:
            continue
        x = read_audio(sp.wav, channels=1)
        i = int(sc["voice_at"] * SR)
        n = min(len(x), len(out) - i)
        out[i:i + n] += x[:n]
    return out


def music_bed(music: Path | None, total: float, style: str, scenes: list[dict], log=print) -> np.ndarray:
    n = int(total * SR) + 1
    if music:
        x = read_audio(music, channels=2)
        if len(x) == 0:
            raise RuntimeError(f"music file {music} decoded to nothing")
        reps = int(np.ceil(n / len(x)))
        if reps > 1:
            log(f"  music is shorter than the video, looping it x{reps}")
        return np.tile(x, (reps, 1))[:n]
    log(f"  no music file: synthesizing a '{style}' music bed")
    return synth_music(style, total, scenes)


def _rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12)


def duck_envelope(scenes: list[dict], speeches: list, total: float, duck: float,
                  attack: float = 0.25, release: float = 0.6, bridge: float = 1.2) -> np.ndarray:
    """Music gain: 1.0 in the gaps, `duck` while someone speaks. Short gaps are
    bridged so the music doesn't pump up between scenes."""
    spans = sorted((sc["voice_at"], sc["voice_at"] + sp.duration)
                   for sc, sp in zip(scenes, speeches) if sp is not None)
    merged = []
    for s, e in spans:
        if merged and s - merged[-1][1] < bridge:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    n = int(total * SR) + 1
    t = np.arange(n) / SR
    g = np.ones(n, dtype=np.float32)
    for s, e in merged:
        # smooth ramps down before speech starts and back up after it ends
        down = np.clip((t - (s - attack)) / attack, 0, 1)
        up = np.clip(((e + release) - t) / release, 0, 1)
        k = np.minimum(down, up)
        k = 0.5 - 0.5 * np.cos(np.pi * k)  # raised-cosine shape
        g = np.minimum(g, 1 - (1 - duck) * k)
    return g


def mix(scenes, speeches, total, music: Path | None, cfg: dict, out_wav: Path, mood: str | None = None,
        with_voice: bool = True, log=print):
    a = cfg["audio"]
    if with_voice:
        v = voice_track(scenes, speeches, total)
    else:
        v = np.zeros((int(total * SR) + 1, 1), dtype=np.float32)
    style = a.get("music_style", "auto")
    if style == "auto":
        style = style_for(mood)
    m = music_bed(music, total, style, scenes, log)
    m *= 10 ** ((float(a["music_level_db"]) - _rms_db(m)) / 20)
    if with_voice:
        m *= duck_envelope(scenes, speeches, total, float(a["music_duck"]))[:, None]
    n = len(m)
    t = np.arange(n) / SR
    fade = np.minimum(np.clip(t / float(a["fade_in"]), 0, 1), np.clip((total - t) / float(a["fade_out"]), 0, 1))
    m *= fade[:, None].astype(np.float32)
    # voice centred in both channels; leave headroom, loudnorm sets the final level
    x = m + v
    if a.get("sfx", True):
        fx = sfx_track(scenes, total, float(cfg["timing"]["transition"]))
        # sfx level is relative to the voice peak; without a voice, to the music peak
        peak = float(np.max(np.abs(v))) or float(np.max(np.abs(m))) or 0.89
        x += fx * (peak * 10 ** (float(a.get("sfx_level_db", -6)) / 20) / (np.max(np.abs(fx)) + 1e-9))
    x *= 0.5 / (np.max(np.abs(x)) + 1e-9)
    raw = out_wav.with_suffix(".raw.wav")
    write_wav(raw, x, SR)
    loudnorm(raw, out_wav, float(a["target_lufs"]), float(a["true_peak"]))
    raw.unlink()


def loudnorm(src: Path, dst: Path, lufs: float, tp: float) -> dict:
    """Two-pass EBU R128 normalisation with ffmpeg's loudnorm filter."""
    base = f"loudnorm=I={lufs}:TP={tp}:LRA=11"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", base + ":print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(re.findall(r"\{[^{}]*\}", r.stderr, re.S)[-1])
    second = (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
              f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", second, "-ar", str(SR),
                    str(dst)], check=True)
    return m


def measure_lufs(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128=framelog=quiet",
                        "-f", "null", "-"], capture_output=True, text=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
