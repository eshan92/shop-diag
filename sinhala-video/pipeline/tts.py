"""Text-to-speech for Sinhala narration.

Engines (tried in the order given by config `tts.engine_order`):
  edge   - Microsoft Edge online TTS via the `edge-tts` package (needs internet,
           unofficial use of Microsoft's service). Best quality.
  mms    - Meta MMS-TTS Sinhala (`facebook/mms-tts-sin`) via Hugging Face
           transformers. Runs offline on CPU once the model is cached.
  espeak - espeak-ng `si` voice. Robotic, but always available offline.

Every engine output is normalised to a mono 48 kHz WAV with leading/trailing
silence trimmed, and cached under cache/tts/ keyed by engine + settings + text.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .audio_io import SR, read_audio, write_wav


class TTSError(RuntimeError):
    pass


@dataclass
class Speech:
    wav: Path
    duration: float
    engine: str
    # word timings relative to the (trimmed) audio: [(start, end, word), ...]
    words: list = field(default_factory=list)


def _trim_silence(x: np.ndarray, thresh_db: float = -45.0, keep: float = 0.05):
    """Trim leading/trailing silence. Returns (trimmed, seconds_cut_at_start)."""
    if len(x) == 0:
        return x, 0.0
    win = int(SR * 0.01)
    n = len(x) // win
    if n == 0:
        return x, 0.0
    frames = x[: n * win].reshape(n, win)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    loud = np.where(20 * np.log10(rms) > thresh_db)[0]
    if len(loud) == 0:
        return x, 0.0
    start = max(0, loud[0] * win - int(keep * SR))
    end = min(len(x), (loud[-1] + 1) * win + int(keep * SR))
    return x[start:end], start / SR


# ----------------------------------------------------------------- engines

def _edge(text: str, cfg: dict, tmp: Path):
    try:
        import edge_tts
    except ImportError as e:
        raise TTSError("edge-tts not installed (pip install edge-tts)") from e

    async def run():
        kwargs = dict(voice=cfg["voice"], rate=cfg.get("rate", "+0%"),
                      pitch=cfg.get("pitch", "+0Hz"), volume=cfg.get("volume", "+0%"))
        if cfg.get("proxy"):
            kwargs["proxy"] = cfg["proxy"]
        try:
            com = edge_tts.Communicate(text, boundary="WordBoundary", **kwargs)
        except TypeError:  # older edge-tts without `boundary`
            com = edge_tts.Communicate(text, **kwargs)
        audio, words = bytearray(), []
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append((s, s + chunk["duration"] / 1e7, chunk["text"]))
        return bytes(audio), words

    try:
        audio, words = asyncio.run(asyncio.wait_for(run(), timeout=60))
    except Exception as e:  # network errors, service changes, ...
        raise TTSError(f"edge-tts failed: {type(e).__name__}: {e}") from e
    if not audio:
        raise TTSError("edge-tts returned no audio")
    mp3 = tmp / "edge.mp3"
    mp3.write_bytes(audio)
    return read_audio(mp3, channels=1), words


_MMS = {}


def _mms(text: str, cfg: dict, tmp: Path):
    try:
        import torch
        from transformers import AutoTokenizer, VitsModel
    except ImportError as e:
        raise TTSError("MMS needs: pip install torch transformers "
                       "(CPU wheel: --index-url https://download.pytorch.org/whl/cpu)") from e
    name = cfg.get("model", "facebook/mms-tts-sin")
    try:
        if name not in _MMS:
            _MMS[name] = (AutoTokenizer.from_pretrained(name),
                          VitsModel.from_pretrained(name).eval())
        tok, model = _MMS[name]
        model.speaking_rate = float(cfg.get("speaking_rate", 1.0))
        torch.manual_seed(int(cfg.get("seed", 1234)))
        inputs = tok(text, return_tensors="pt")
        if inputs["input_ids"].shape[-1] == 0:
            raise TTSError("MMS tokenizer produced no tokens for this text")
        with torch.no_grad():
            wav = model(**inputs).waveform[0].cpu().numpy().astype(np.float32)
        sr = model.config.sampling_rate
    except TTSError:
        raise
    except Exception as e:
        raise TTSError(f"MMS-TTS failed: {type(e).__name__}: {e}") from e
    raw = tmp / "mms.wav"
    write_wav(raw, wav[:, None], sr)
    return read_audio(raw, channels=1), []


def _espeak(text: str, cfg: dict, tmp: Path):
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise TTSError("espeak-ng not installed (sudo apt install espeak-ng)")
    out = tmp / "espeak.wav"
    r = subprocess.run([exe, "-v", cfg.get("voice", "si"), "-s", str(cfg.get("speed", 140)),
                        "-w", str(out), text], capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        raise TTSError(f"espeak-ng failed: {r.stderr.strip()}")
    return read_audio(out, channels=1), []


ENGINES = {"edge": _edge, "mms": _mms, "espeak": _espeak}


# ------------------------------------------------------------------ public

class TTS:
    def __init__(self, tts_cfg: dict, cache_dir: Path, offline: bool = False, log=print):
        order = list(tts_cfg.get("engine_order", ["edge", "mms", "espeak"]))
        if offline:
            order = [e for e in order if e != "edge"]
        unknown = [e for e in order if e not in ENGINES]
        if unknown:
            raise ValueError(f"unknown TTS engine(s) in config: {unknown}")
        self.order = order
        self.cfg = tts_cfg
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.log = log
        self.dead = set()  # engines that failed once: don't retry every scene

    def _key(self, engine: str, text: str) -> str:
        blob = json.dumps([engine, self.cfg.get(engine, {}), text], sort_keys=True,
                          ensure_ascii=False)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def speak(self, text: str) -> Speech:
        errors = []
        for engine in self.order:
            if engine in self.dead:
                continue
            key = self._key(engine, text)
            wav, meta = self.cache / f"{key}.wav", self.cache / f"{key}.json"
            if wav.exists() and meta.exists():
                m = json.loads(meta.read_text())
                return Speech(wav, m["duration"], engine, [tuple(w) for w in m["words"]])
            try:
                with tempfile.TemporaryDirectory() as td:
                    audio, words = ENGINES[engine](text, self.cfg.get(engine, {}), Path(td))
            except TTSError as e:
                self.log(f"  ! {engine}: {e}")
                errors.append(str(e))
                self.dead.add(engine)
                continue
            audio, cut = _trim_silence(audio[:, 0])
            if len(audio) < SR * 0.1:
                errors.append(f"{engine}: produced (almost) silent audio")
                continue
            peak = float(np.max(np.abs(audio))) or 1.0
            audio = audio * (0.89 / peak)  # -1 dBFS peak; loudness is fixed in the final mix
            dur = len(audio) / SR
            words = [(max(0.0, s - cut), min(dur, e - cut), w) for s, e, w in words]
            write_wav(wav, audio[:, None], SR)
            meta.write_text(json.dumps({"duration": dur, "words": words, "engine": engine,
                                        "text": text}, ensure_ascii=False))
            return Speech(wav, dur, engine, words)
        raise TTSError("all TTS engines failed:\n  " + "\n  ".join(errors))
