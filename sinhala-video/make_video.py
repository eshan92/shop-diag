#!/usr/bin/env python3
"""Turn a scene script (JSON) into an animated Sinhala explainer video.

  python make_video.py scripts/sample.json --format shorts     # 1080x1920
  python make_video.py scripts/sample.json --format youtube    # 1920x1080
  python make_video.py scripts/sample.json --format both
  python make_video.py scripts/sample.json --preview-only      # contact sheet only, no TTS
  python make_video.py scripts/sample.json --offline           # skip edge-tts
  python make_video.py scripts/sample.json --no-voice          # music + sound effects + subtitles only
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pipeline.audio_io import probe_duration  # noqa: E402
from pipeline.mix import measure_lufs, mix  # noqa: E402
from pipeline.render import preview_and_check, render_video  # noqa: E402
from pipeline.timeline import build_timeline, load_script  # noqa: E402
from pipeline.tts import TTS, Speech  # noqa: E402

FORMATS = {"shorts": (1080, 1920), "youtube": (1920, 1080)}


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = {
        "channel_tag": "", "subscribe_text": "SUBSCRIBE", "sources_label": "Sources",
        "tts": {"engine_order": ["edge", "mms", "espeak"],
                "edge": {"voice": "si-LK-ThiliniNeural"}, "mms": {}, "espeak": {}},
        "timing": {"fps": 30, "padding": 0.6, "min_scene": 2.5, "no_narration_scene": 3.0,
                   "voice_lead_in": 0.15, "transition": 0.5, "outro_hold": 1.5},
        "subtitles": {"enabled": True, "max_words": 4, "max_chars": 32},
        "audio": {"music_style": "auto", "sfx": True, "sfx_level_db": -6, "music_duck": 0.15, "music_level_db": -20, "fade_in": 1.0, "fade_out": 2.0,
                  "target_lufs": -14, "true_peak": -1.5},
        "render": {"jpeg_quality": 92, "crf": 18, "preset": "medium", "workers": 0},
    }
    for k, v in defaults.items():
        if isinstance(v, dict):
            cfg[k] = {**v, **(cfg.get(k) or {})}
        else:
            cfg.setdefault(k, v)
    return cfg


def next_output(out_dir: Path, name: str, fmt: str) -> Path:
    v = 1
    while (out_dir / f"{name}_{fmt}_v{v}.mp4").exists():
        v += 1
    return out_dir / f"{name}_{fmt}_v{v}.mp4"


def find_music(script: dict, script_path: Path, override: str | None) -> Path | None:
    m = override or script.get("music")
    if not m:
        return None
    for base in (Path.cwd(), ROOT, script_path.parent, ROOT / "music"):
        p = (base / m)
        if p.is_file():
            return p
    print(f"  ! music file '{m}' not found - using the synthesized drone instead")
    return None


def estimate_speech(text: str) -> Speech:
    # ~13 Sinhala characters per second of speech; used by --preview-only
    return Speech(wav=None, duration=max(1.0, len(text.replace(" ", "")) / 13), engine="estimate")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path)
    ap.add_argument("--format", choices=["shorts", "youtube", "both"], default="shorts")
    ap.add_argument("--offline", action="store_true", help="don't use edge-tts (MMS / espeak only)")
    ap.add_argument("--no-voice", action="store_true",
                    help="no voiceover: background music + sound effects only (subtitles still shown, "
                         "timed at a normal reading pace)")
    ap.add_argument("--preview-only", action="store_true",
                    help="only write the contact sheet + layout check (estimated timings, no TTS)")
    ap.add_argument("--music", help="override the script's music file")
    ap.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    ap.add_argument("--workers", type=int, help="parallel render workers (default: config)")
    ap.add_argument("--strict", action="store_true", help="stop if the layout check finds problems")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    args = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found - sudo apt install ffmpeg")
    cfg = load_config(args.config)
    if args.workers:
        cfg["render"]["workers"] = args.workers
    script, warnings = load_script(args.script)
    for w in warnings:
        print(f"  ! {w}")
    name = args.script.stem
    args.out.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    # 1) voice ------------------------------------------------------------------
    print(f"[1/4] voice for {len(script['scenes'])} scenes")
    speeches = []
    if args.preview_only or args.no_voice:
        if args.no_voice:
            print("  --no-voice: no voiceover, scene lengths from estimated reading time")
        speeches = [estimate_speech(s["narration"]) if (s.get("narration") or "").strip() else None
                    for s in script["scenes"]]
    else:
        tts = TTS(cfg["tts"], ROOT / "cache" / "tts", offline=args.offline)
        for i, s in enumerate(script["scenes"], 1):
            text = (s.get("narration") or "").strip()
            if not text:
                print(f"  scene {i}: no narration -> {cfg['timing']['no_narration_scene']}s")
                speeches.append(None)
                continue
            sp = tts.speak(text)
            print(f"  scene {i}: {sp.duration:5.2f}s  ({sp.engine}{', word timings' if sp.words else ''})")
            speeches.append(sp)
        used = sorted({sp.engine for sp in speeches if sp})
        if used and used != ["edge"]:
            print(f"  note: voice engine(s) used: {', '.join(used)}")

    scenes, cues, total = build_timeline(script, speeches, cfg)
    print(f"  total length {total:.2f}s, {len(cues)} subtitle cues")

    formats = ["shorts", "youtube"] if args.format == "both" else [args.format]
    srcs = script.get("sources") or []
    base_data = {
        "fps": int(cfg["timing"]["fps"]), "palette": script["palette"], "total": total,
        "transition": float(cfg["timing"]["transition"]), "scenes": scenes, "cues": cues,
        "channel_tag": cfg.get("channel_tag", ""), "subscribe_text": cfg.get("subscribe_text", ""),
        "sources_text": f"{cfg.get('sources_label', 'Sources')}: {' · '.join(srcs)}" if srcs else "",
    }

    # 2) audio mix (shared by all formats) -------------------------------------
    work = Path(tempfile.mkdtemp(prefix=".work_", dir=args.out))
    try:
        mix_wav = work / "mix.wav"
        if not args.preview_only:
            print("[2/4] audio mix")
            mood = script.get("music_mood") or (script.get("meta") or {}).get("music_mood")
            mix(scenes, speeches, total, find_music(script, args.script, args.music), cfg, mix_wav, mood,
                with_voice=not args.no_voice)
            print(f"  loudness {measure_lufs(mix_wav):.1f} LUFS (target {cfg['audio']['target_lufs']})")

        for fmt in formats:
            w, h = FORMATS[fmt]
            data = {**base_data, "width": w, "height": h}
            out = next_output(args.out, name + ("_novoice" if args.no_voice else ""), fmt)
            sheet = out.with_name(out.stem + "_preview.png")
            print(f"[3/4] {fmt} {w}x{h}: preview + layout check -> {sheet.name}")
            issues = preview_and_check(data, sheet)
            for msg in issues:
                print(f"  ! layout: {msg}")
            if not issues:
                print("  layout OK: no overlaps, nothing off-screen, headlines <= 5 lines")
            if issues and args.strict:
                sys.exit("layout problems found (--strict)")
            if args.preview_only:
                continue
            print(f"[4/4] {fmt}: render -> {out.name}")
            silent = work / f"{fmt}.mp4"
            render_video(data, silent, cfg["render"])
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(mix_wav),
                            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                            "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)],
                            check=True)
            vdur = probe_duration(out)
            print(f"  done: {out}  ({vdur:.2f}s, {out.stat().st_size / 1e6:.1f} MB)")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"finished in {time.time() - t_start:.0f}s")


if __name__ == "__main__":
    main()
