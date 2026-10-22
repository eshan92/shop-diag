"""Script loading, voice-driven scene timing and subtitle cues."""
from __future__ import annotations

import json
import re
from pathlib import Path

ICONS = {"pin", "people", "scale", "calendar", "globe", "phone", "subscribe", "none"}
ANIMATIONS = {"slide-left", "slide-right", "zoom", "typewriter", "fade", "bounce"}
TRANSITIONS = {"fade", "wipe", "zoom"}
DEFAULT_PALETTE = {"bg": "#0D0D0D", "accent": "#E50914", "text": "#FFFFFF", "muted": "#B0B0B0"}


def load_script(path: Path) -> tuple[dict, list[str]]:
    """Load + validate a script. Returns (script, warnings)."""
    s = json.loads(Path(path).read_text(encoding="utf-8"))
    warn = []
    if not s.get("scenes"):
        raise ValueError(f"{path}: no scenes")
    s["palette"] = {**DEFAULT_PALETTE, **(s.get("palette") or {})}
    for i, sc in enumerate(s["scenes"], 1):
        if not str(sc.get("headline", "")).strip():
            warn.append(f"scene {i}: empty headline")
        for key, allowed, default in (("icon", ICONS, "none"), ("animation", ANIMATIONS, "fade"),
                                      ("transition", TRANSITIONS, "fade")):
            v = str(sc.get(key) or default).strip().lower()
            if v not in allowed:
                warn.append(f"scene {i}: unknown {key} '{v}', using '{default}'")
                v = default
            sc[key] = v
    return s, warn


_PUNCT = re.compile(r"[\s.,!?;:\"'“”‘’()\[\]{}\-–—…।]+")


def _weight(word: str) -> float:
    # rough proxy for spoken length: visible characters, ignoring signs that
    # don't add a syllable (virama, ZWJ) and punctuation
    core = _PUNCT.sub("", word).replace("‍", "").replace("්", "")
    return max(1, len(core)) + (2.0 if re.search(r"[.!?।,;:]$", word) else 0.0)  # pauses


def chunk_words(text: str, max_words: int, max_chars: int) -> list[list[str]]:
    chunks, cur = [], []
    for w in text.split():
        if cur and (len(cur) >= max_words or len(" ".join(cur + [w])) > max_chars):
            chunks.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?।]$", w):  # sentence end -> start a new chunk
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def word_times(words: list[str], speech) -> list[tuple[float, float]]:
    """Start/end time of each word within the scene audio."""
    tts = speech.words if speech else []
    if tts and len(tts) == len(words):
        return [(s, e) for s, e, _ in tts]
    if tts and len(tts) > 1:
        # different tokenisation: map by relative position in the text
        total = sum(len(w) for w in words) or 1
        out, pos = [], 0
        for w in words:
            k = min(len(tts) - 1, int(pos / total * len(tts)))
            out.append((tts[k][0], tts[k][1]))
            pos += len(w)
        return out
    dur = speech.duration if speech else 0
    ws = [_weight(w) for w in words]
    tot = sum(ws) or 1
    out, acc = [], 0.0
    for w in ws:
        out.append((dur * acc / tot, dur * (acc + w) / tot))
        acc += w
    return out


def build_timeline(script: dict, speeches: list, cfg: dict) -> tuple[list[dict], list[dict], float]:
    """Scene start/duration from the voice, plus absolute subtitle cues."""
    tm, st = cfg["timing"], cfg["subtitles"]
    lead = float(tm.get("voice_lead_in", 0.15))
    scenes, cues, t = [], [], 0.0
    n = len(script["scenes"])
    for i, (sc, sp) in enumerate(zip(script["scenes"], speeches)):
        if sp is not None:
            dur = max(float(tm["min_scene"]), sp.duration + float(tm["padding"]))
        else:
            dur = float(tm["no_narration_scene"])
        if i == n - 1:
            dur += float(tm.get("outro_hold", 0))
        scenes.append({**sc, "start": round(t, 4), "dur": round(dur, 4), "is_last": i == n - 1,
                       "voice_at": round(t + lead, 4) if sp else None})
        if sp is not None and st.get("enabled", True):
            words = sc["narration"].split()
            times = word_times(words, sp)
            idx = 0
            for ch in chunk_words(sc["narration"], int(st["max_words"]), int(st["max_chars"])):
                s0, e0 = times[idx][0], times[idx + len(ch) - 1][1]
                cues.append({"start": round(t + lead + s0, 3), "end": round(t + lead + e0, 3),
                             "text": " ".join(ch)})
                idx += len(ch)
            # hold each cue until the next one in the same scene starts (no flicker)
            scene_cues = [c for c in cues if c["start"] >= t]
            for a, b in zip(scene_cues, scene_cues[1:]):
                a["end"] = b["start"]
            if scene_cues:
                scene_cues[-1]["end"] = round(min(t + dur, scene_cues[-1]["end"] + 0.35), 3)
        t += dur
    return scenes, cues, round(t, 4)
