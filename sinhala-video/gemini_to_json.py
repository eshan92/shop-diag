#!/usr/bin/env python3
"""Convert Gemini's storyboard text into a scripts/<name>.json scene script.

Understands the usual layout (markdown bold/headings are ignored):

    TITLE: ...
    COLOR PALETTE: Black #0D0D0D (background), Red #E50914 (accent), ...
    SCENES
    Scene 1 (0-5s)
    On-screen text: "..."
    Visual: ...
    Animation: Slide in from left
    Transition: Fade
    Scene 2 ...
    VOICEOVER SCRIPT
    [Scene 1] ... or just paragraphs
    SOURCES: Gulf News, The Daily Star        (optional)

The voiceover is assigned to scenes by "Scene N" markers when present,
otherwise split into sentences and spread across scenes in order.

  python gemini_to_json.py gemini.txt                   -> scripts/gemini.json
  python gemini_to_json.py gemini.txt -o scripts/x.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_PALETTE = {"bg": "#0D0D0D", "accent": "#E50914", "text": "#FFFFFF", "muted": "#B0B0B0"}

ICON_WORDS = [  # first match wins
    ("subscribe", r"subscrib|like button|bell|channel|follow"),
    ("phone", r"phone|call|mobile|smartphone|whatsapp|sms|app\b|message|text message"),
    ("calendar", r"calendar|date|deadline|year|month|week|day|schedule|time ?line|clock"),
    ("pin", r"\bpin\b|location|map\b|city|place|address|district|province|airport"),
    ("scale", r"law|court|justice|legal|scale|balance|judge|rule|regulation|fine|penalt|rights"),
    ("globe", r"globe|world|international|countr|global|abroad|foreign|earth"),
    ("people", r"people|crowd|worker|citizen|famil|population|person|men|women|student|migrant|users?\b"),
]


def clean(line: str) -> str:
    line = re.sub(r"^[#>\s]*", "", line)               # headings / quotes
    line = re.sub(r"^\s*[-*•]\s+", "", line)           # bullets
    return line.replace("**", "").replace("__", "").strip()


def unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'“‘" and s[-1] in "\"'”’":
        s = s[1:-1]
    return s.strip()


def pick_animation(text: str) -> str:
    t = text.lower()
    if "type" in t:
        return "typewriter"
    if "bounce" in t or "pop" in t or "spring" in t:
        return "bounce"
    if "zoom" in t or "scale" in t or "grow" in t or "punch" in t:
        return "zoom"
    if "slide" in t or "swipe" in t or "fly" in t or "enter" in t:
        # "slide in from the left" moves rightwards -> slide-right
        from_left = "from left" in t or "from the left" in t
        to_right = "right" in t and "from right" not in t and "from the right" not in t
        if from_left or to_right:
            return "slide-right"
        return "slide-left"
    return "fade"


def pick_transition(text: str) -> str:
    t = text.lower()
    if "wipe" in t or "swipe" in t or "slide" in t or "push" in t:
        return "wipe"
    if "zoom" in t or "scale" in t:
        return "zoom"
    return "fade"


def pick_icon(*texts: str) -> str:
    # the Visual description wins over the on-screen text
    for t in texts:
        for icon, pat in ICON_WORDS:
            if re.search(pat, t.lower()):
                return icon
    return "none"


def parse_palette(text: str) -> dict:
    pal = dict(DEFAULT_PALETTE)
    named, unnamed = {}, []
    roles = (("bg", r"background|\bbg\b|base"), ("accent", r"accent|highlight|primary|pop"),
             ("text", r"\btext\b|font|headline|foreground|main"), ("muted", r"muted|secondary|grey|gray|sub"))
    # one colour per item: items are separated by newlines, commas or semicolons
    for item in re.split(r"[\n,;]", text):
        m = re.search(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", item)
        if not m:
            continue
        hexv, ctx = m.group(0).upper(), item.lower()
        for key, pat in roles:
            if key not in named and re.search(pat, ctx):
                named[key] = hexv
                break
        else:
            unnamed.append(hexv)
    for key in ("bg", "accent", "text", "muted"):  # unlabelled colours fill the gaps in order
        if key not in named and unnamed:
            named[key] = unnamed.pop(0)
    pal.update(named)
    return pal


def split_sections(lines):
    """-> dict(title, palette, scenes_lines, voice_lines, sources_lines)"""
    sec, out = None, {"title": "", "palette": "", "scenes": [], "voice": [], "sources": []}
    for raw in lines:
        line = clean(raw)
        up = line.upper()
        m = re.match(r"^TITLE\s*[:\-–]\s*(.*)$", line, re.I)
        if m:
            out["title"] = unquote(m.group(1)); sec = None
            continue
        if re.match(r"^COLOU?R\s*PALETTE", up):
            sec = "palette"; out["palette"] += (line.split(":", 1)[1] if ":" in line else "") + "\n"
            continue
        if re.match(r"^(VOICE[\s-]*OVER|NARRATION)(\s*SCRIPT)?\s*:?\s*$", up) or \
                re.match(r"^(VOICE[\s-]*OVER|NARRATION)\s*SCRIPT\s*:", up):
            sec = "voice"
            rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if rest:
                out["voice"].append(rest)
            continue
        if re.match(r"^SCENES?\s*(BREAKDOWN|LIST)?\s*:?\s*$", up):
            sec = "scenes"
            continue
        m = re.match(r"^(SOURCES?|REFERENCES?|CREDITS?)\s*:?\s*(.*)$", line, re.I)
        if m and (sec != "voice" or not m.group(2) or up.startswith("SOURCE")):
            sec = "sources"
            if m.group(2):
                out["sources"].append(m.group(2))
            continue
        if sec not in ("scenes", "voice") and re.match(r"^SCENE\s*\d+", up):
            sec = "scenes"
        if sec == "palette":
            out["palette"] += line + "\n"
        elif sec in ("scenes", "voice", "sources"):
            out[sec].append(line)
    return out


FIELD = re.compile(r"^(on[\s-]*screen\s*text|text|headline|visuals?|animation|transition|"
                   r"sub(?:title|text)?|note|voice[\s-]*over|narration)\s*:\s*(.*)$", re.I)


def parse_scenes(lines):
    scenes, cur, field = [], None, None
    for line in lines:
        if not line:
            continue
        if re.match(r"^SCENE\s*\d+", line, re.I):
            cur = {"onscreen": [], "visual": "", "animation": "", "transition": "", "voice": ""}
            scenes.append(cur)
            field = None
            # "Scene 1: Hook - text" -> keep anything after a colon as a label only
            continue
        if cur is None:
            continue
        m = FIELD.match(line)
        if m:
            key = m.group(1).lower().replace(" ", "").replace("-", "")
            val = m.group(2).strip()
            if key in ("onscreentext", "text", "headline"):
                field = "onscreen"
                if val:
                    cur["onscreen"].append(val)
            elif key.startswith("visual"):
                field = "visual"; cur["visual"] = val
            elif key == "animation":
                field = "animation"; cur["animation"] = val
            elif key == "transition":
                field = "transition"; cur["transition"] = val
            elif key in ("voiceover", "narration"):
                field = "voice"; cur["voice"] = val
            else:
                field = "onscreen"
                if val:
                    cur["onscreen"].append(val)
            continue
        if field == "onscreen":
            cur["onscreen"].append(line)
        elif field in ("visual", "animation", "transition", "voice"):
            cur[field] = (cur[field] + " " + line).strip()
    return scenes


def onscreen_parts(items):
    """On-screen text lines -> headline, sub, note."""
    parts = []
    for it in items:
        # several quoted strings on one line: "Headline" + "Subline"
        q = re.findall(r"[\"“]([^\"”]+)[\"”]", it)
        parts += q if q else [unquote(p) for p in re.split(r"\s+[|/]\s+|\s+[—–]\s+", it)]
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return "", "", ""
    return parts[0], (parts[1] if len(parts) > 1 else ""), " ".join(parts[2:])


def split_sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?।])\s+", text) if s.strip()]


def assign_voiceover(voice_lines, n):
    text = "\n".join(voice_lines).strip()
    if not text or n == 0:
        return [""] * n
    # explicit markers: "[Scene 2]", "Scene 2:", "(Scene 2)"
    marks = list(re.finditer(r"[\[(]?\bscene\s*(\d+)\b[^\])\n:]*[\])]?\s*[:\-–]?", text, re.I))
    if marks:
        out = [""] * n
        for k, m in enumerate(marks):
            idx = int(m.group(1)) - 1
            end = marks[k + 1].start() if k + 1 < len(marks) else len(text)
            chunk = " ".join(text[m.end():end].split())
            if 0 <= idx < n:
                out[idx] = (out[idx] + " " + chunk).strip()
        return [unquote(o) for o in out]
    # no markers: spread sentences over the scenes, balancing characters
    text = " ".join(unquote(l) for l in voice_lines if l and not re.match(r"^\(.*\)$", l))
    sents = split_sentences(text)
    if len(sents) <= n:
        return sents + [""] * (n - len(sents))
    total = sum(len(s) for s in sents)
    out, k, acc = [[] for _ in range(n)], 0, 0
    for i, s in enumerate(sents):
        left_s, left_scenes = len(sents) - i, n - k
        # move to the next scene once this one has its share, but keep at
        # least one sentence for every remaining scene
        if out[k] and k < n - 1 and (acc >= total * (k + 1) / n or left_s <= left_scenes - 1):
            k += 1
        out[k].append(s)
        acc += len(s)
    return [" ".join(o) for o in out]


def convert(text: str) -> dict:
    sec = split_sections(text.splitlines())
    scenes_raw = parse_scenes(sec["scenes"])
    if not scenes_raw:
        raise ValueError("no 'Scene N' blocks found")
    inline_voice = [s["voice"] for s in scenes_raw]
    voice = inline_voice if any(inline_voice) and not sec["voice"] else \
        assign_voiceover(sec["voice"], len(scenes_raw))
    sources = []
    for l in sec["sources"]:
        sources += [unquote(s) for s in re.split(r"\s*[,;]\s*|\s+and\s+", l) if s.strip()]
    scenes = []
    for i, (s, v) in enumerate(zip(scenes_raw, voice)):
        head, sub, note = onscreen_parts(s["onscreen"])
        last = i == len(scenes_raw) - 1
        icon = pick_icon(s["visual"], head)
        if last and re.search(r"subscrib|follow|like", (s["visual"] + head + v).lower()):
            icon = "subscribe"
        sc = {"headline": head, "sub": sub, "note": note, "narration": v.strip(), "icon": icon,
              "animation": pick_animation(s["animation"]), "transition": pick_transition(s["transition"])}
        scenes.append({k: val for k, val in sc.items() if val != "" or k in ("headline", "narration")})
    return {"title": sec["title"], "palette": parse_palette(sec["palette"]), "music": "",
            "sources": sources, "scenes": scenes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path, help="Gemini text file ('-' for stdin)")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    text = sys.stdin.read() if str(args.input) == "-" else args.input.read_text(encoding="utf-8")
    data = convert(text)
    out = args.output or Path(__file__).resolve().parent / "scripts" / f"{args.input.stem}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(data['scenes'])} scenes, palette {data['palette']}")
    for i, s in enumerate(data["scenes"], 1):
        print(f"  {i}. [{s['icon']}/{s['animation']}/{s['transition']}] {s['headline'][:50]}"
              f"  | voice: {len(s['narration'])} chars")
    print("Now translate/edit the headline, sub, note and narration fields to Sinhala.")


if __name__ == "__main__":
    main()
