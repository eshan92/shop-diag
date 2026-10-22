# Sinhala explainer video pipeline

This tool turns a scene script (JSON) into an animated Sinhala explainer video with AI voiceover, burned-in subtitles,
background music and a subscribe outro. It makes 1080x1920 for Shorts/Reels and 1920x1080 for YouTube/Facebook.
Everything runs locally and uses no paid APIs.

```
scripts/x.json ─► TTS per scene ─► scene timings from voice length ─► HTML template (Playwright, render(t))
                                                                   └► JPEG frames ─► ffmpeg x264
               └► voice track + music bed (ducked to 15%) ─► loudnorm -14 LUFS ─► mux ─► output/x_shorts_v1.mp4
```

## Setup (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3-pip ffmpeg espeak-ng fonts-dejavu-core
cd sinhala-video
pip install -r requirements.txt
python3 -m playwright install --with-deps chromium

# optional: offline neural voice (Meta MMS-TTS, CPU). Model (~150 MB) downloads on first use.
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install transformers
```

The fonts are already bundled in `assets/fonts`: Noto Sans Sinhala (OFL) and DejaVu Sans for Latin
digits and symbols. To refresh them from npm, run `tools/update_fonts.sh` (it runs `npm i @fontsource/noto-sans-sinhala`).

## Usage

```bash
python3 make_video.py scripts/sample.json --format shorts    # 1080x1920
python3 make_video.py scripts/sample.json --format youtube   # 1920x1080
python3 make_video.py scripts/sample.json --format both
python3 make_video.py scripts/sample.json --preview-only     # contact sheet + layout check, ~10 s, no TTS
python3 make_video.py scripts/sample.json --offline          # skip edge-tts, use MMS (then espeak-ng)
python3 make_video.py scripts/sample.json --music music/dramatic.mp3   # override the script's music
```

Output goes to `output/`:

- `<name>_<format>_v1.mp4`. Existing files are never overwritten: the next run writes `_v2`, `_v3`, …
- `<name>_<format>_vN_preview.png`: a contact sheet with one settled frame per scene. Each label shows the scene's
  duration, its animation/transition and how many lines the headline takes.

Before rendering, every run checks the layout for each scene and prints any problems: overlapping elements,
anything off-screen or in the subtitle zone, headlines over 5 lines, and subtitles over 2 lines.
`--strict` stops the run if the check finds anything.

### From Gemini

```bash
python3 gemini_to_json.py gemini.txt                 # -> scripts/gemini.json
python3 gemini_to_json.py gemini.txt -o scripts/uae_visa.json
```

The converter reads TITLE, COLOR PALETTE, SCENES ("On-screen text", "Visual", "Animation", "Transition"),
VOICEOVER SCRIPT and an optional SOURCES line. If the voiceover has `[Scene N]` / `Scene N:` markers, it
follows them. If not, it splits the voiceover into sentences and spreads them across the scenes. It picks an
icon from the Visual text and maps the animation and transition wording onto the supported names. It also handles the
`Scene 1 | 0s–3s` / `Transition to next:` / `VOICEOVER SCRIPT (optional):` layout, palettes without labels
(colours are sorted into background, text, muted grey and accent by how they look; a spare brand colour
becomes `accent2`, which tints the background glow), and invisible zero-width characters copied from Gemini.
Unknown sections such as YOUTUBE DESCRIPTION, HASHTAGS and MUSIC MOOD are kept under `"meta"` for
uploading and are not rendered. Translate or edit the text fields to Sinhala afterwards. See `examples/` and `gemini/`.

## Script format

```json
{
  "title": "...",
  "palette": {"bg": "#0D0D0D", "accent": "#E50914", "text": "#FFFFFF", "muted": "#B0B0B0"},
  "music": "music/dramatic.mp3",
  "sources": ["Gulf News", "The Daily Star"],
  "scenes": [
    {
      "headline": "සිංහල headline, *accent word* in asterisks",
      "sub": "optional smaller line",
      "note": "optional small accent line",
      "narration": "සිංහල voiceover text for this scene",
      "icon": "pin|people|scale|calendar|globe|phone|subscribe|none",
      "icon_value": "optional, e.g. 24h or 1,200+ (count-up on calendar/people)",
      "animation": "slide-left|slide-right|zoom|typewriter|fade|bounce",
      "transition": "fade|wipe|zoom"
    }
  ]
}
```

- **Scene length follows the voice:** narration length + 0.6 s, with a 2.5 s minimum. A scene with no narration
  lasts 3 s, and the last scene gets 1.5 s extra for the subscribe button. All of these are in `config.yaml`.
- **Last scene:** shows the sources credit line and a bouncing subscribe button.
- **Subtitles:** narration is split into chunks of up to 4 words / 32 characters. Chunks are timed from edge-tts
  word boundaries when available. Otherwise the timing is estimated from text length.
- **Headline size:** if a headline would take more than 5 lines, its font is shrunk automatically. If a whole
  scene doesn't fit, all of its elements are shrunk together.

## Voices

| Engine | Quality | Needs | Notes |
|---|---|---|---|
| `edge` | best | internet | `edge-tts`, voices `si-LK-ThiliniNeural` (female) / `si-LK-SameeraNeural` (male). Unofficial use of Microsoft's Edge read-aloud service. It can change or stop working at any time. |
| `mms` | good | offline after the first download | `facebook/mms-tts-sin` (CC-BY-NC 4.0, so check the license before monetised use) |
| `espeak` | robotic | offline | last resort so a render never fails |

Engines are tried in the order set by `tts.engine_order`. If one fails, the run falls back to the next and
prints a warning. Voice, rate and pitch are set in `config.yaml`. TTS results are cached in `cache/tts/`, so a
re-render doesn't call the voice service again. Delete that folder to force new voice files.

## Audio

- **Music:** from the script's `music` (searched relative to the current folder, the project folder and
  `music/`). A track shorter than the video is looped. With no track, a dark ambient drone is synthesized with numpy.
- **Ducking:** volume automation, not a compressor. Music drops to 15% while someone speaks, and short gaps
  between scenes are bridged so the music doesn't pump. It fades in over 1 s and out over 2 s.
- **Loudness:** the final mix is normalised with two-pass `loudnorm` to -14 LUFS, -1.5 dBTP.

## Speed

The 54 s sample takes about 3 minutes per format on 4 CPU cores. Rendering is split across parallel browser
workers (`render.workers` in `config.yaml`, or `--workers N`). Use `--preview-only` while editing text.

## Files

```
make_video.py        CLI
gemini_to_json.py    Gemini storyboard -> script JSON
config.yaml          voice, timing, subtitle, audio and render settings
pipeline/tts.py      edge-tts / MMS / espeak-ng with fallback + cache
pipeline/timeline.py scene timing + subtitle cues
pipeline/mix.py      voice track, music/drone, ducking, loudnorm
pipeline/render.py   Playwright frames -> ffmpeg, contact sheet, layout check
template/            index.html + engine.js (render(t)) + icons.js (inline SVG icons)
assets/fonts/        Noto Sans Sinhala + DejaVu Sans (with licenses)
```
