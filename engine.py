"""Shorts Studio engine: voiceover, stock footage, captions, 9:16 render.

No Streamlit imports here so it can be tested and reused on its own.
"""
import asyncio
import difflib
import random
import re
import shutil
import subprocess
from pathlib import Path

import requests

VOICES = {
    "English (India) - Female": "en-IN-NeerjaNeural",
    "English (India) - Male": "en-IN-PrabhatNeural",
    "Hindi - Female": "hi-IN-SwaraNeural",
    "Hindi - Male": "hi-IN-MadhurNeural",
    "Telugu - Female": "te-IN-ShrutiNeural",
    "Telugu - Male": "te-IN-MohanNeural",
    "Tamil - Female": "ta-IN-PallaviNeural",
    "Tamil - Male": "ta-IN-ValluvarNeural",
}


# ---------- helpers ----------
def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd[:4]))}...\n{r.stderr[-1500:]}")
    return r


def media_duration(path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


# ---------- voiceover ----------
async def _tts(text, voice, rate, mp3_path):
    import edge_tts
    try:
        com = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions emit word boundaries by default
        com = edge_tts.Communicate(text, voice, rate=rate)
    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((chunk["text"], start, start + chunk["duration"] / 1e7))
    return words


def synthesize(text, voice, rate_percent, mp3_path):
    """Returns list of (word, start_sec, end_sec). rate_percent: -30..+40."""
    rate = f"{rate_percent:+d}%"
    return asyncio.run(_tts(text, voice, rate, str(mp3_path)))


# ---------- captions ----------
def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(words, script_text, audio_seconds, words_per_caption=3, upper=True) -> str:
    """Word-timed captions. Falls back to even spacing if no timings came back."""
    if not words:
        toks = script_text.split()
        step = audio_seconds / max(len(toks), 1)
        words = [(w, i * step, (i + 1) * step) for i, w in enumerate(toks)]
    lines = []
    for i in range(0, len(words), words_per_caption):
        grp = words[i:i + words_per_caption]
        start, end = grp[0][1], grp[-1][2]
        text = " ".join(w[0] for w in grp)
        text = text.upper() if upper else text
        lines.append((start, end, text))
    # close tiny gaps so captions do not flicker
    out = []
    for idx, (s, e, t) in enumerate(lines):
        if idx + 1 < len(lines):
            e = max(e, min(lines[idx + 1][0], e + 0.25))
        out.append(f"{idx + 1}\n{_ts(s)} --> {_ts(e)}\n{t}\n")
    return "\n".join(out)


# ---------- stock footage (Pexels, free API key) ----------
def pexels_clip(query, api_key, cache_dir, used, orientation="portrait"):
    """orientation: 'portrait' for Shorts/Reels, 'landscape' for normal YouTube videos."""
    r = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": orientation, "per_page": 15},
        timeout=30,
    )
    r.raise_for_status()
    vids = r.json().get("videos", [])
    random.shuffle(vids)
    for v in vids:
        if v["id"] in used:
            continue
        files = [f for f in v.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("width") and f["width"] <= 1080]
        if not files:
            continue
        best = max(files, key=lambda f: f["width"])
        dest = Path(cache_dir) / f"pexels_{v['id']}.mp4"
        if not dest.exists():
            with requests.get(best["link"], stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as fh:
                    for part in resp.iter_content(1 << 20):
                        fh.write(part)
        used.add(v["id"])
        return dest
    return None


# ---------- render ----------
SIZES = {"short": (1080, 1920), "long": (1920, 1080)}


def render_video(clips, audio_path, srt_text, out_path, kind="short", font="Arial", font_size=None,
                 music_path=None, music_volume=0.08, max_seg_seconds=8.0):
    """Stitch clips to 1080x1920 (short) or 1920x1080 (long), add voice (+ optional quiet music),
    burn captions. Clips are cycled so no single clip stays on screen longer than max_seg_seconds."""
    w, h = SIZES[kind]
    if font_size is None:
        font_size = 14 if kind == "short" else 16
    margin_v = 60 if kind == "short" else 22
    out_path = Path(out_path)
    work = out_path.parent / f".work_{out_path.stem}"
    work.mkdir(parents=True, exist_ok=True)
    total = media_duration(audio_path) + 0.3
    n_segs = max(len(clips), int(-(-total // max_seg_seconds)))
    seg = total / n_segs

    seg_files = []
    for i in range(n_segs):
        c = clips[i % len(clips)]
        sf = work / f"seg{i}.mp4"
        _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(c), "-t", f"{seg:.3f}",
              "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps=30,setsar=1",
              "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(sf)])
        seg_files.append(sf)

    (work / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in seg_files), encoding="utf-8")
    (work / "captions.srt").write_text(srt_text, encoding="utf-8")
    shutil.copy(audio_path, work / "voice.mp3")

    style = (f"FontName={font},FontSize={font_size},Bold=1,PrimaryColour=&H00FFFFFF,"
             f"OutlineColour=&H00000000,BorderStyle=1,Outline=3,Shadow=1,Alignment=2,MarginV={margin_v}")
    vf = f"[0:v]subtitles=captions.srt:force_style='{style}'[v]"

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", "voice.mp3"]
    if music_path:
        shutil.copy(music_path, work / "music.mp3")
        cmd += ["-stream_loop", "-1", "-i", "music.mp3"]
        af = (f";[2:a]volume={music_volume}[m];[1:a][m]amix=inputs=2:duration=first:"
              "dropout_transition=0,volume=2[a]")
        amap = "[a]"
    else:
        af, amap = "", "1:a"
    cmd += ["-filter_complex", vf + af, "-map", "[v]", "-map", amap,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
            str(out_path.resolve())]
    _run(cmd, cwd=str(work))
    shutil.rmtree(work, ignore_errors=True)
    return out_path


def render_short(*args, **kwargs):  # backwards-compatible name
    return render_video(*args, kind="short", **kwargs)


# ---------- thumbnail (long videos) ----------
def _find_font(size, font_path=None):
    from PIL import ImageFont
    cands = [font_path] if font_path else []
    cands += ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "NotoSans-Bold.ttf"]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default(size)


def make_thumbnail(video_path, title, out_path, font_path=None, at_seconds=2.0):
    """1280x720 JPG: a frame from the video plus a big bold title. Uses your own title text only."""
    import textwrap
    from PIL import Image, ImageDraw
    frame = Path(out_path).with_suffix(".frame.jpg")
    _run(["ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video_path), "-frames:v", "1",
          "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720", str(frame)])
    img = Image.open(frame).convert("RGB")
    shade = Image.new("RGB", img.size, (0, 0, 0))
    mask = Image.linear_gradient("L").resize(img.size)  # black at top -> white at bottom
    img = Image.composite(shade, img, mask.point(lambda p: int(p * 0.65)))
    d = ImageDraw.Draw(img)
    font = _find_font(96, font_path)
    lines = textwrap.wrap(title.upper(), width=18)[:3]
    y = 720 - 60 - len(lines) * 110
    for ln in lines:
        d.text((60, y), ln, font=font, fill="white", stroke_width=6, stroke_fill="black")
        y += 110
    img.save(out_path, "JPEG", quality=92)
    frame.unlink(missing_ok=True)
    return Path(out_path)


# ---------- AI draft (Claude API) ----------
DRAFT_SYSTEM = """You help a solo creator draft an ORIGINAL, genuinely useful faceless video.
Return ONLY a JSON object, no markdown fences, with these keys:
  "title": string, max 90 chars, accurate and specific, no clickbait lies, no ALL CAPS spam
  "script": string, the narration only (no stage directions, no emojis), written in the requested language
  "keywords": array of short ENGLISH stock-footage search phrases (concrete visual things),
              about one per 6-8 seconds of narration
  "description": string, 2-4 sentences plus 3-5 hashtags
  "tags": array of up to 8 short tags
Rules: educational and honest. Do not invent statistics, quotes, studies or product claims. No income
promises or guaranteed results. For finance or health topics give general education only, no personal
advice. Open with a hook in the first sentence, give concrete value, end with a one-line call to action."""


def parse_draft(raw: str) -> dict:
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1:
        raise ValueError("AI reply did not contain JSON.")
    import json
    d = json.loads(raw[s:e + 1])
    for k in ("title", "script", "keywords"):
        if k not in d:
            raise ValueError(f"AI reply is missing '{k}'.")
    d.setdefault("description", "")
    d.setdefault("tags", [])
    return d


def ai_draft(idea, niche, language, kind, minutes, api_key, model="claude-sonnet-5-5"):
    """Ask Claude to draft script + footage keywords + metadata. The user must still review and edit."""
    target = "about 100 to 130 words (a 40 to 55 second Short)" if kind == "short" \
        else f"about {int(minutes * 140)} words (roughly {minutes} minutes spoken)"
    msg = (f"Niche: {niche}\nVideo idea: {idea}\nLanguage for the script: {language}\n"
           f"Length: {target}\nFormat: {'vertical Short' if kind == 'short' else 'normal YouTube video'}")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 4096, "system": DRAFT_SYSTEM,
              "messages": [{"role": "user", "content": msg}]},
        timeout=90,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Claude API error {r.status_code}: {r.text[:300]}")
    return parse_draft("".join(b.get("text", "") for b in r.json().get("content", [])))


# ---------- policy guards ----------
def script_problems(text: str, kind: str = "short"):
    """Quality gate so the tool cannot be used to mass-produce thin content."""
    words = len(text.split())
    lo, hi = (40, 170) if kind == "short" else (250, 1500)
    problems = []
    if words < lo:
        problems.append(f"Script is too short (under {lo} words). Add a real tip, example or opinion.")
    if words > hi:
        problems.append(f"Script is too long (over {hi} words) for this format.")
    return problems


def max_similarity(text: str, previous):
    return max((difflib.SequenceMatcher(None, text.lower(), p.lower()).ratio() for p in previous),
               default=0.0)


def make_metadata(topic: str, niche: str, hook: str):
    topic = topic.strip().rstrip(".")
    title = (hook.strip() or topic)[:90]
    tags = ["Shorts"] + [re.sub(r"\W+", "", w.title()) for w in (niche + " " + topic).split()[:4] if len(w) >= 2]
    desc = (f"{topic}\n\nFollow for one useful {niche} tip every day.\n\n"
            + " ".join("#" + t for t in tags[:5]))
    return title, desc
