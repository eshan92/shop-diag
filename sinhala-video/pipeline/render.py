"""Frame rendering: Playwright (headless Chromium) -> JPEG frames -> ffmpeg (libx264)."""
from __future__ import annotations

import glob
import io
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TEMPLATE = Path(__file__).resolve().parent.parent / "template" / "index.html"
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _chromium_candidates():
    env = os.environ.get("CHROMIUM_PATH")
    if env:
        yield env
    pats = ["/opt/pw-browsers/chromium-*/chrome-linux*/chrome",
            os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")]
    for pat in pats:
        yield from sorted(glob.glob(pat), reverse=True)
    for name in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(name):
            yield shutil.which(name)


def launch(p):
    """Launch Playwright's Chromium; fall back to any local Chromium if the
    bundled build doesn't match the installed playwright version."""
    args = ["--font-render-hinting=none", "--disable-lcd-text", "--hide-scrollbars",
            "--force-color-profile=srgb"]
    try:
        return p.chromium.launch(args=args)
    except Exception as first:
        for exe in _chromium_candidates():
            try:
                return p.chromium.launch(executable_path=exe, args=args)
            except Exception:
                continue
        raise RuntimeError("Could not start Chromium. Run: python -m playwright install chromium "
                           "(or set CHROMIUM_PATH)") from first


def open_page(p, data):
    browser = launch(p)
    page = browser.new_page(viewport={"width": data["width"], "height": data["height"]},
                            device_scale_factor=1)
    page.goto(TEMPLATE.as_uri())
    fit = page.evaluate("d => init(d)", data)
    return browser, page, fit


def settle_time(scene, transition):
    """A moment inside the scene where entrance animations are finished."""
    return scene["start"] + max(transition + 0.05, min(scene["dur"] - 0.1, 2.2))


def _ffmpeg_encode(out: Path, fps: int, cfg: dict):
    return subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg",
         "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
         "-c:v", "libx264", "-preset", cfg.get("preset", "medium"), "-crf", str(cfg.get("crf", 18)),
         "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-color_range", "tv", "-r", str(fps), str(out)],
        stdin=subprocess.PIPE)


def _render_range(data, f0, f1, out, cfg):
    from playwright.sync_api import sync_playwright
    fps, q = data["fps"], int(cfg.get("jpeg_quality", 92))
    with sync_playwright() as p:
        browser, page, _ = open_page(p, data)
        enc = _ffmpeg_encode(Path(out), fps, cfg)
        try:
            for f in range(f0, f1):
                page.evaluate("t => render(t)", f / fps)
                enc.stdin.write(page.screenshot(type="jpeg", quality=q))
        finally:
            enc.stdin.close()
            enc.wait()
            browser.close()
    if enc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed encoding frames {f0}-{f1}")
    return f1 - f0


def render_video(data: dict, out: Path, cfg: dict, log=print) -> None:
    """Render all frames to a silent H.264 file, in parallel chunks."""
    fps = data["fps"]
    n = int(round(data["total"] * fps))
    workers = int(cfg.get("workers", 0)) or min(4, os.cpu_count() or 1)
    workers = max(1, min(workers, n // (fps * 2) or 1))  # >= 2 s per chunk
    bounds = [round(n * k / workers) for k in range(workers + 1)]
    with tempfile.TemporaryDirectory(dir=out.parent) as td:
        segs = [Path(td) / f"seg{k:02d}.mp4" for k in range(workers)]
        log(f"  rendering {n} frames ({data['total']:.1f}s @ {fps}fps) with {workers} worker(s)...")
        if workers == 1:
            _render_range(data, 0, n, str(segs[0]), cfg)
        else:
            with ProcessPoolExecutor(workers) as ex:
                futs = [ex.submit(_render_range, data, bounds[k], bounds[k + 1], str(segs[k]), cfg)
                        for k in range(workers)]
                for f in futs:
                    f.result()
        lst = Path(td) / "list.txt"
        lst.write_text("".join(f"file '{s.name}'\n" for s in segs))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(out)], check=True)


def preview_and_check(data: dict, sheet_path: Path, log=print):
    """Render one settled frame per scene into a contact sheet, and run layout checks.
    Returns a list of human-readable layout issues (empty = all good)."""
    from playwright.sync_api import sync_playwright
    issues, thumbs = [], []
    with sync_playwright() as p:
        browser, page, fit = open_page(p, data)
        for i, sc in enumerate(data["scenes"]):
            t = settle_time(sc, data["transition"])
            page.evaluate("t => render(t)", t)
            for msg in page.evaluate("i => checkScene(i)", i):
                issues.append(f"scene {i + 1}: {msg}")
            img = Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")
            thumbs.append((img, f"#{i + 1}  {sc['dur']:.1f}s  {sc.get('animation', '')}/{sc.get('transition', '')}"
                                f"  headline {fit[i]['lines']} line(s)"
                                + (f"  font x{fit[i]['hscale']}" if fit[i]['hscale'] < 1 else "")))
        issues += page.evaluate("() => checkCues()")
        browser.close()
    _contact_sheet(thumbs, data["width"] > data["height"], sheet_path)
    return issues


def _contact_sheet(thumbs, landscape, path: Path):
    cols = 3 if landscape else 4
    tw = 560 if landscape else 360
    w0, h0 = thumbs[0][0].size
    th = round(h0 * tw / w0)
    label_h, pad = 34, 14
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (pad + cols * (tw + pad), pad + rows * (th + label_h + pad)), (24, 24, 24))
    try:
        font = ImageFont.truetype(str(FONT_DIR / "DejaVuSans.ttf"), 15)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for k, (img, label) in enumerate(thumbs):
        x = pad + (k % cols) * (tw + pad)
        y = pad + (k // cols) * (th + label_h + pad)
        sheet.paste(img.resize((tw, th), Image.LANCZOS), (x, y + label_h))
        d.text((x, y + 8), label, fill=(230, 230, 230), font=font)
    sheet.save(path)
