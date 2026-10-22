"""Tiny audio helpers built on ffmpeg + numpy (no extra Python audio deps)."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000


def read_audio(path, channels: int = 2, sr: int = SR) -> np.ndarray:
    """Decode any audio file with ffmpeg -> float32 array of shape (n, channels)."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le",
         "-ac", str(channels), "-ar", str(sr), "-"],
        capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {path}: {r.stderr.decode()[-400:]}")
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, channels).copy()


def write_wav(path, x: np.ndarray, sr: int = SR) -> None:
    """Write float audio (n, channels) in [-1, 1] as 16-bit PCM WAV."""
    if x.ndim == 1:
        x = x[:, None]
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def probe_duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())
