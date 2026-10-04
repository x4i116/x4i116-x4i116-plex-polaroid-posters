#!/usr/bin/env python3
"""
plex_polaroid.py - Give every movie and TV show in Plex a matching minimalist
"polaroid" style poster: the poster in a square frame on an off-white
background, a bold title and year, then running time / director / producer
(movies) or network / seasons / episodes (shows), and top-billed stars.
Every season of a show also gets its own poster with its season number,
year and episode count. With --episodes, every episode also gets a wide
thumbnail in the same style.

See README.md for setup. Quick reference:

    python plex_polaroid.py --url URL --token TOKEN --dry-run --limit 10   preview only
    python plex_polaroid.py --url URL --token TOKEN                        apply to library
    python plex_polaroid.py --url URL --token TOKEN --force                redo everything
    python plex_polaroid.py --url URL --token TOKEN --restore              put originals back

A --force redo remembers its progress: if it's interrupted, running it again
(or --continue) picks up where it stopped. --fresh starts the redo over.

Other options: --library NAME (repeat for several), --episodes, --no-seasons, --only "Title", --use-still, --backup-dir DIR.
--url / --token / --library can also come from the PLEX_URL / PLEX_TOKEN /
PLEX_LIBRARY environment variables (PLEX_LIBRARY can list several, separated by ;).
"""

import argparse
import json
import io
import os
import sys
import time
from pathlib import Path

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

try:
    import cv2

    cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
except Exception:
    cv2 = None  # face detection unavailable; detail-based cropping is used instead

LABEL = "polaroid"
FONT_DIR = Path(__file__).resolve().parent / "fonts"
# (google/fonts path, local filename, variable-font weight or None)
FONTS = {
    "title": ("ofl/oswald/Oswald%5Bwght%5D.ttf", "Oswald-Variable.ttf", 700),
    "serif": ("ofl/crimsontext/CrimsonText-Regular.ttf", "CrimsonText-Regular.ttf", None),
}

# ---- Layout (1000 x 1500, matched to the reference poster) ---------------
W, H = 1000, 1500
BG = (222, 217, 211)
INK = (43, 41, 40)
M = 54  # outer margin
IMG = W - 2 * M  # square still, 892 px
TITLE_CAP = 74  # cap height of the title letters
TITLE_TOP = M + IMG + 58  # top of title caps
SERIF_SIZE = 40
YEAR_SIZE = 39
LINE_GAP = 63  # between info lines
STAR_EXTRA = 38  # extra gap before "starring"
LABEL_GAP = 30  # space between "directed by" and the name
NAME_GAP = 30  # space between starring names
BOTTOM = H - 70  # lowest allowed baseline


def font(kind, size):
    src, local, weight = FONTS[kind]
    path = FONT_DIR / local
    if not path.exists():
        FONT_DIR.mkdir(exist_ok=True)
        r = requests.get("https://github.com/google/fonts/raw/main/" + src, timeout=30)
        r.raise_for_status()
        path.write_bytes(r.content)
    f = ImageFont.truetype(str(path), size)
    if weight:
        f.set_variation_by_axes([weight])
    return f


def title_font_for_cap(cap):
    """Title font size whose capital letters are `cap` px tall."""
    probe = font("title", 100)
    l, t, r, b = probe.getbbox("H")
    return font("title", round(100 * cap / (b - t)))


def fmt_runtime(ms):
    if not ms:
        return None
    mins = round(ms / 60000)
    h, m = divmod(mins, 60)
    return f"{h}h {m}min" if h else f"{m}min"


# --------------------------------------------------------------------------
# Smart square crop
# --------------------------------------------------------------------------
def find_faces(gray):
    if cv2 is None:
        return []
    faces = []
    mins = max(12, int(min(gray.shape) * 0.08))
    for name in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        cas = cv2.CascadeClassifier(cv2.data.haarcascades + name)
        for x, y, w, h in cas.detectMultiScale(gray, 1.1, 6, minSize=(mins, mins)):
            faces.append((x + w / 2, y + h / 2, float(w * h)))
    return faces


def busiest_offset(gray, horizontal, window, bias_to):
    """Slide a window along one axis and find where the most detail is."""
    g = gray.astype(np.float32)
    energy = np.abs(np.diff(g, axis=0))[:, :-1] + np.abs(np.diff(g, axis=1))[:-1, :]
    profile = energy.sum(axis=0 if horizontal else 1)
    n = len(profile)
    window = min(window, n)
    sums = np.convolve(profile, np.ones(window), "valid")
    if len(sums) <= 1:
        return 0
    pos = np.arange(len(sums)) / (len(sums) - 1)
    sums = sums * (1 - 0.35 * np.abs(pos - bias_to))  # gently prefer the usual spot
    return int(np.argmax(sums))


def square_crop(img, focus=None):
    """Crop to a square. focus=0..1 forces the position along the long side."""
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    horizontal = w > h
    span = (w if horizontal else h) - side
    if span <= 0:
        return img

    if focus is not None:
        start = int(span * max(0.0, min(1.0, focus)))
    else:
        scale = 480 / max(w, h)
        small = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
        gray = np.asarray(small.convert("L"))
        faces = find_faces(gray)
        if faces:
            wt = [a * a for _, _, a in faces]  # bigger faces count much more
            c = sum((fx if horizontal else fy) * k for (fx, fy, _), k in zip(faces, wt)) / sum(wt)
            centre = c / scale
            if not horizontal:
                centre += side * 0.1  # leave headroom above faces
            start = int(centre - side / 2)
        else:
            off = busiest_offset(gray, horizontal, int(side * scale), 0.5 if horizontal else 0.3)
            start = int(off / scale)
        start = max(0, min(span, start))

    box = (start, 0, start + side, side) if horizontal else (0, start, side, start + side)
    return img.crop(box)


def fit_whole(poster):
    """Whole poster, uncropped, centred in the square. The empty sides are
    filled with a soft blurred copy of the same poster."""
    poster = poster.convert("RGB")
    back = ImageOps.fit(poster, (IMG, IMG), Image.LANCZOS)
    back = back.filter(ImageFilter.GaussianBlur(28))
    back = ImageEnhance.Brightness(back).enhance(0.75)
    w, h = poster.size
    s = min(IMG / w, IMG / h)
    front = poster.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    back.paste(front, ((IMG - front.width) // 2, (IMG - front.height) // 2))
    return back


def make_poster(
    still,
    title,
    year=None,
    runtime=None,
    directors=(),
    producers=(),
    stars=(),
    focus=None,
    whole=False,
    rows=None,
):
    """rows: optional list of (label, [values]) to use instead of the movie
    rows (running time / directed by / produced by) - used for TV shows."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Square still
    if whole:
        photo = fit_whole(still)
    else:
        photo = square_crop(still, focus).resize((IMG, IMG), Image.LANCZOS)
    img.paste(photo, (M, M))

    # Year (right aligned)
    yfont = font("serif", YEAR_SIZE)
    year_txt = str(year) if year else ""
    year_w = d.textlength(year_txt, font=yfont) if year_txt else 0

    # Title: one line, shrinking if long; two lines if it gets too small
    text = title.upper()
    max_w = IMG - (year_w + 40 if year_w else 0)
    cap = TITLE_CAP
    tfont = title_font_for_cap(cap)
    while d.textlength(text, font=tfont) > max_w and cap > TITLE_CAP * 0.6:
        cap -= 2
        tfont = title_font_for_cap(cap)
    lines = [text]
    if d.textlength(text, font=tfont) > max_w:
        cap = int(TITLE_CAP * 0.72)
        tfont = title_font_for_cap(cap)
        words, lines = text.split(), [""]
        for w in words:
            trial = (lines[-1] + " " + w).strip()
            limit = max_w if len(lines) == 1 else IMG
            if d.textlength(trial, font=tfont) <= limit or not lines[-1]:
                lines[-1] = trial
            else:
                lines.append(w)
        lines = lines[:2]
        while any(d.textlength(l, font=tfont) > IMG for l in lines) and cap > 30:
            cap -= 2
            tfont = title_font_for_cap(cap)

    baseline = TITLE_TOP + cap
    line_h = int(cap * 1.28)
    for i, l in enumerate(lines):
        d.text((M - 2, baseline + i * line_h), l, font=tfont, fill=INK, anchor="ls")
    if year_txt:
        d.text((M + IMG, TITLE_TOP + TITLE_CAP - 8), year_txt, font=yfont, fill=INK, anchor="rs")
    title_bottom = baseline + (len(lines) - 1) * line_h

    # Info lines
    sfont = font("serif", SERIF_SIZE)
    if rows is not None:
        rows = [(label, list(vals)[:2]) for label, vals in rows if vals]
    else:
        rows = []
        if runtime:
            rows.append(("running time", [runtime]))
        if directors:
            rows.append(("directed by", list(directors)[:2]))
        if producers:
            rows.append(("produced by", list(producers)[:2]))
    stars = list(stars)[:3]

    gap = LINE_GAP
    n = len(rows) + (1 if stars else 0)
    first = title_bottom + 80
    needed = first + (n - 1) * gap + (STAR_EXTRA if stars else 0)
    if needed > BOTTOM and n > 1:
        gap = max(44, (BOTTOM - first - (STAR_EXTRA if stars else 0)) // (n - 1))

    def draw_row(y, label, names):
        x = M + 2
        d.text((x, y), label, font=sfont, fill=INK, anchor="ls")
        x += d.textlength(label, font=sfont) + LABEL_GAP
        shown = []
        for nm in names:  # drop names that won't fit rather than overflow
            w = d.textlength(nm, font=sfont)
            if x + w > M + IMG and shown:
                break
            shown.append((x, nm))
            x += w + NAME_GAP
        for xx, nm in shown:
            d.text((xx, y), nm, font=sfont, fill=INK, anchor="ls")

    y = first
    for label, names in rows:
        draw_row(y, label, names)
        y += gap
    if stars:
        draw_row(y + (STAR_EXTRA if rows else 0), "starring", stars)
    return img


# --------------------------------------------------------------------------
# Plex
# --------------------------------------------------------------------------
def fetch_image(server, path):
    r = requests.get(server.url(path, includeToken=True), timeout=120)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content))


def load_overrides(path):
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.rsplit("=", 1)
                out[k.strip().lower()] = v.strip().lower()
    return out


def safe_name(movie):
    keep = "".join(c for c in movie.title if c.isalnum() or c in " -_").strip()
    return f"{keep} ({movie.year}) [{movie.ratingKey}]"


def retry(fn, what="request", tries=4):
    """Run a Plex call, waiting and retrying if Plex is slow to answer."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt == tries:
                raise
            wait = 15 * attempt
            print(f"   Plex didn't answer ({what}), retrying in {wait}s...")
            time.sleep(wait)


class RedoProgress:
    """Remembers what a --force redo has already finished, so an interrupted
    redo picks up where it stopped instead of starting over. The first line
    stores which libraries/options the redo was started with."""

    def __init__(self, path):
        self.path = path
        self.settings = {}
        self.ids = set()
        if path.exists():
            lines = path.read_text().splitlines()
            if lines and lines[0].startswith("#"):
                try:
                    self.settings = json.loads(lines[0][1:])
                except ValueError:
                    pass
                lines = lines[1:]
            self.ids = {l.strip() for l in lines if l.strip()}

    def __contains__(self, key):
        return str(key) in self.ids

    def start(self, args):
        if not self.path.exists():
            self.settings = {
                "libraries": args.library,
                "episodes": bool(args.episodes),
                "no_seasons": bool(args.no_seasons),
            }
            self.path.write_text("#" + json.dumps(self.settings) + "\n")

    def add(self, key):
        if str(key) not in self.ids:
            self.ids.add(str(key))
            with open(self.path, "a") as f:
                f.write(f"{key}\n")

    def clear(self):
        self.ids = set()
        self.settings = {}
        self.path.unlink(missing_ok=True)


REDO = None  # set in run() during a --force redo


def already_redone(key):
    return REDO is not None and key in REDO


def mark_redone(key):
    if REDO is not None:
        REDO.add(key)


def process_movie(movie, i, total, args, server, backups, preview, overrides):
    name = safe_name(movie)
    labels = retry(lambda: [l.tag.lower() for l in movie.labels], "labels")

    if args.restore:
        backup = backups / f"{name}.jpg"
        if LABEL in labels and backup.exists():
            print(f"[{i}/{total}] restoring {movie.title}")
            retry(lambda: movie.uploadPoster(filepath=str(backup)), "upload")
            retry(lambda: movie.removeLabel(LABEL), "label")
            return "done"
        return "ignored"

    if LABEL in labels and not args.force:
        return "skipped"
    if already_redone(movie.ratingKey):
        return "skipped"

    print(f"[{i}/{total}] {movie.title} ({movie.year})")
    retry(movie.reload, "movie details")  # full cast / crew lists

    # Back up the current poster (only the first time)
    backup = backups / f"{name}.jpg"
    if movie.thumb and not backup.exists():
        img = retry(lambda: fetch_image(server, movie.thumb), "poster download")
        img.convert("RGB").save(backup, quality=95)

    # Per-movie override: a number (crop position) or "poster"
    ov = overrides.get(movie.title.lower()) or overrides.get(
        f"{movie.title} ({movie.year})".lower()
    )
    focus = None
    if ov and ov != "poster":
        try:
            focus = float(ov)
        except ValueError:
            print(f"   ignoring bad override '{ov}'")

    # Default: the whole original poster. --use-still: cropped background art
    whole = not (args.use_still and movie.art and ov != "poster")
    if not whole:
        still = retry(lambda: fetch_image(server, movie.art), "still download")
    elif backup.exists():
        still = Image.open(backup)
    else:
        print("   no artwork to work from, skipping")
        return "skipped"

    if movie.type == "show":
        seasons = [x for x in retry(movie.seasons, "seasons") if x.index != 0]  # skip Specials
        n_seasons = len(seasons) or movie.childCount
        out = make_poster(
            still,
            movie.title,
            movie.year,
            rows=[
                ("network", [movie.studio] if movie.studio else []),
                ("seasons", [str(n_seasons)] if n_seasons else []),
                ("episodes", [str(movie.leafCount)] if movie.leafCount else []),
            ],
            stars=[r.tag for r in movie.roles],
            focus=focus,
            whole=whole,
        )
    else:
        out = make_poster(
            still,
            movie.title,
            movie.year,
            runtime=fmt_runtime(movie.duration),
            directors=[p.tag for p in movie.directors],
            producers=[p.tag for p in getattr(movie, "producers", [])],
            stars=[r.tag for r in movie.roles],
            focus=focus,
            whole=whole,
        )

    if args.dry_run:
        preview.mkdir(exist_ok=True)
        out.save(preview / f"{name}.jpg", quality=92)
    else:
        tmp = backups / "_upload.jpg"
        out.save(tmp, quality=92)
        retry(lambda: movie.uploadPoster(filepath=str(tmp)), "upload")
        retry(movie.lockPoster, "lock")  # stop Plex from swapping it back
        if LABEL not in labels:
            retry(lambda: movie.addLabel(LABEL), "label")
        tmp.unlink(missing_ok=True)
        mark_redone(movie.ratingKey)
        time.sleep(0.5)  # give Plex a breather
    return "done"


_RELOADED = set()


def season_labels(season, backups):
    """Labels on a season. Older Plex servers can't label seasons, so fall
    back to a small list of finished season IDs kept in the backup folder."""
    try:
        return retry(lambda: [l.tag.lower() for l in season.labels], "labels")
    except AttributeError:
        done_file = backups / "_done_seasons.txt"
        ids = done_file.read_text().split() if done_file.exists() else []
        return [LABEL] if str(season.ratingKey) in ids else []


def set_season_label(season, backups, on):
    try:
        if on:
            retry(lambda: season.addLabel(LABEL), "label")
        else:
            retry(lambda: season.removeLabel(LABEL), "label")
    except AttributeError:
        done_file = backups / "_done_seasons.txt"
        ids = set(done_file.read_text().split()) if done_file.exists() else set()
        (ids.add if on else ids.discard)(str(season.ratingKey))
        done_file.write_text("\n".join(sorted(ids)))


def process_season(show, season, args, server, backups, preview):
    """Give one season its own poster: show title, the season's year, then
    season number, episode count, network and the show's stars."""
    label_name = "Specials" if season.index == 0 else f"Season {season.index}"
    keep = "".join(c for c in show.title if c.isalnum() or c in " -_").strip()
    name = f"{keep} - {label_name} [{season.ratingKey}]"
    labels = season_labels(season, backups)
    backup = backups / f"{name}.jpg"

    if args.restore:
        if LABEL in labels and backup.exists():
            print(f"      restoring {label_name}")
            retry(lambda: season.uploadPoster(filepath=str(backup)), "upload")
            set_season_label(season, backups, False)
            return "done"
        return "ignored"

    if LABEL in labels and not args.force:
        return "skipped"
    if already_redone(season.ratingKey):
        return "skipped"

    print(f"      {label_name}")

    # Back up the season's own poster. Seasons without one borrow the show's.
    if season.thumb and not backup.exists():
        img = retry(lambda: fetch_image(server, season.thumb), "poster download")
        img.convert("RGB").save(backup, quality=95)
    show_backup = backups / f"{safe_name(show)}.jpg"
    source = backup if backup.exists() else show_backup
    if not source.exists():
        print("         no artwork to work from, skipping")
        return "skipped"

    if show.ratingKey not in _RELOADED:  # full cast list, once per show
        retry(show.reload, "show details")
        _RELOADED.add(show.ratingKey)

    # Season year: Plex's own, or the year its first episode aired
    year = getattr(season, "year", None)
    if not year:
        try:
            eps = retry(season.episodes, "episodes")
            dates = [e.originallyAvailableAt for e in eps if e.originallyAvailableAt]
            year = min(dates).year if dates else show.year
        except Exception:
            year = show.year

    out = make_poster(
        Image.open(source),
        show.title,
        year,
        rows=[
            ("season", ["specials" if season.index == 0 else str(season.index)]),
            ("episodes", [str(season.leafCount)] if season.leafCount else []),
            ("network", [show.studio] if show.studio else []),
        ],
        stars=[r.tag for r in show.roles],
        whole=True,
    )

    if args.dry_run:
        preview.mkdir(exist_ok=True)
        out.save(preview / f"{name}.jpg", quality=92)
    else:
        tmp = backups / "_upload.jpg"
        out.save(tmp, quality=92)
        retry(lambda: season.uploadPoster(filepath=str(tmp)), "upload")
        retry(season.lockPoster, "lock")
        if LABEL not in labels:
            set_season_label(season, backups, True)
        tmp.unlink(missing_ok=True)
        mark_redone(season.ratingKey)
        time.sleep(0.5)
    return "done"


# --------------------------------------------------------------------------
# Episode cards (wide, because Plex shows episode thumbnails as 16:9)
# --------------------------------------------------------------------------
EW, EH = 1600, 900
EM = 40  # border
ESTRIP = 190  # bottom strip for the text
SUBTLE = (90, 86, 82)


def _truncate(d, text, fnt, max_w):
    if d.textlength(text, font=fnt) <= max_w:
        return text
    while text and d.textlength(text + "\u2026", font=fnt) > max_w:
        text = text[:-1]
    return text.rstrip() + "\u2026"


def make_episode_card(shot, ep_title, show_title, season_no, episode_no, year=None, runtime=None):
    img = Image.new("RGB", (EW, EH), BG)
    d = ImageDraw.Draw(img)
    iw, ih = EW - 2 * EM, EH - EM - ESTRIP
    # Centred: an equal sliver is trimmed off the top and bottom of the screenshot
    photo = ImageOps.fit(shot.convert("RGB"), (iw, ih), Image.LANCZOS, centering=(0.5, 0.5))
    img.paste(photo, (EM, EM))

    # "S2 · E5" on the right
    se_font = font("serif", 44)
    se = f"S{season_no} \u00b7 E{episode_no}" if season_no is not None else f"E{episode_no}"
    se_w = d.textlength(se, font=se_font)

    # Episode title: shrink to fit, then trim with "..." if still too long
    text = (ep_title or f"Episode {episode_no}").upper()
    max_w = iw - se_w - 40
    cap = 64
    tfont = title_font_for_cap(cap)
    while d.textlength(text, font=tfont) > max_w and cap > 46:
        cap -= 2
        tfont = title_font_for_cap(cap)
    text = _truncate(d, text, tfont, max_w)
    base = EM + ih + 40 + 64
    d.text((EM - 2, base), text, font=tfont, fill=INK, anchor="ls")
    d.text((EW - EM, base), se, font=se_font, fill=INK, anchor="rs")

    # Small line: show  ·  aired YEAR  ·  48min
    info_font = font("serif", 34)
    tail = [p for p in (f"aired {year}" if year else None, runtime) if p]
    sep = "   \u00b7   "
    tail_txt = sep + sep.join(tail) if tail else ""
    room = iw - d.textlength(tail_txt, font=info_font)
    line = _truncate(d, show_title, info_font, room) + tail_txt
    d.text((EM + 2, base + 56), line, font=info_font, fill=SUBTLE, anchor="ls")
    return img


class DoneList:
    """Finished episodes are tracked in a file in the backup folder instead of
    Plex labels - much faster to check for thousands of episodes."""

    def __init__(self, path):
        self.path = path
        self.ids = set(path.read_text().split()) if path.exists() else set()

    def __contains__(self, key):
        return str(key) in self.ids

    def add(self, key):
        if str(key) not in self.ids:
            self.ids.add(str(key))
            with open(self.path, "a") as f:
                f.write(f"{key}\n")

    def remove(self, key):
        self.ids.discard(str(key))
        self.path.write_text("".join(f"{k}\n" for k in sorted(self.ids)))


def process_episode(show, ep, args, server, backups, preview, done_eps):
    s_no, e_no = ep.parentIndex, ep.index
    keep = "".join(c for c in show.title if c.isalnum() or c in " -_").strip()
    tag = f"S{s_no or 0:02d}E{e_no or 0:02d}"
    name = f"{keep} - {tag} [{ep.ratingKey}]"
    ep_backups = backups / "episodes"
    ep_backups.mkdir(exist_ok=True)
    backup = ep_backups / f"{name}.jpg"

    if args.restore:
        if ep.ratingKey in done_eps and backup.exists():
            print(f"      restoring {tag}")
            retry(lambda: ep.uploadPoster(filepath=str(backup)), "upload")
            done_eps.remove(ep.ratingKey)
            return "done"
        return "ignored"

    if ep.ratingKey in done_eps and not args.force:
        return "skipped"
    if already_redone(ep.ratingKey):
        return "skipped"

    if not backup.exists():
        if not ep.thumb:
            print(f"      {tag}: no thumbnail in Plex, skipping")
            return "skipped"
        img = retry(lambda: fetch_image(server, ep.thumb), "thumbnail download")
        img.convert("RGB").save(backup, quality=95)

    print(f"      {tag} {ep.title}")
    aired = getattr(ep, "originallyAvailableAt", None)
    out = make_episode_card(
        Image.open(backup),
        ep.title,
        show.title,
        s_no,
        e_no,
        year=aired.year if aired else getattr(ep, "year", None),
        runtime=fmt_runtime(ep.duration),
    )

    if args.dry_run:
        preview.mkdir(exist_ok=True)
        out.save(preview / f"{name}.jpg", quality=90)
    else:
        tmp = backups / "_upload.jpg"
        out.save(tmp, quality=90)
        retry(lambda: ep.uploadPoster(filepath=str(tmp)), "upload")
        retry(ep.lockPoster, "lock")
        done_eps.add(ep.ratingKey)
        tmp.unlink(missing_ok=True)
        mark_redone(ep.ratingKey)
        time.sleep(0.3)
    return "done"


def run(args):
    from plexapi.server import PlexServer

    if cv2 is None and args.use_still:
        print(
            "Note: face detection isn't working (OpenCV missing or broken), so crops\n"
            "will be based on image detail only. Run: pip install opencv-python-headless\n"
        )

    server = PlexServer(args.url, args.token, timeout=120)
    # Keep all output next to the script, no matter where it's run from
    here = Path(__file__).resolve().parent
    backups = Path(args.backup_dir)
    if not backups.is_absolute():
        backups = here / backups
    try:
        backups.mkdir(exist_ok=True)
        (backups / "_write_test").write_text("ok")
        (backups / "_write_test").unlink()
    except PermissionError:
        sys.exit(
            f"Windows won't let Python write to:\n  {backups}\n"
            "Move the PlexPolaroid folder somewhere simple like C:\\PlexPolaroid "
            "and run it from there."
        )
    preview = here / "polaroid_preview"

    overrides = load_overrides(here / "crop_overrides.txt")
    done_eps = DoneList(backups / "_done_episodes.txt")

    # Resumable redo
    global REDO
    progress = RedoProgress(backups / "_redo_progress.txt")
    if args.continue_redo:
        if not progress.path.exists():
            sys.exit("There's no unfinished redo to continue.")
        st = progress.settings
        args.library = st.get("libraries") or args.library
        args.episodes = st.get("episodes", args.episodes)
        args.no_seasons = st.get("no_seasons", args.no_seasons)
        args.force = True
        args.dry_run = args.restore = False
    if args.force and not args.dry_run and not args.restore:
        if args.fresh:
            progress.clear()
        if progress.ids:
            print(
                f"Continuing an unfinished redo: {len(progress.ids)} already redone, "
                "skipping those. (Use --fresh to start the redo over.)"
            )
        progress.start(args)
        REDO = progress

    done = skipped = failed = 0
    in_a_row = 0
    stopped = False
    for lib_name in args.library:
        if stopped:
            break
        try:
            lib = server.library.section(lib_name)
        except Exception:
            names = ", ".join(s.title for s in server.library.sections())
            print(f"\nCan't find a library called '{lib_name}'. Your libraries are: {names}")
            continue
        if lib.type not in ("movie", "show"):
            print(f"\nSkipping '{lib_name}' - only movie and TV libraries are supported.")
            continue
        print(f"\n=== {lib_name} ===")
        movies = retry(lib.all, "library list")
        if args.only:
            movies = [m for m in movies if args.only.lower() in m.title.lower()]
        if args.limit:
            movies = movies[: args.limit]

        for i, movie in enumerate(movies, 1):
            try:
                result = process_movie(
                    movie, i, len(movies), args, server, backups, preview, overrides
                )
                in_a_row = 0
                if result == "done":
                    done += 1
                elif result == "skipped":
                    skipped += 1
                # Seasons get their own posters (even if the show itself was already done)
                if movie.type == "show" and not args.no_seasons:
                    for season in retry(movie.seasons, "seasons"):
                        r = process_season(movie, season, args, server, backups, preview)
                        if r == "done":
                            done += 1
                        elif r == "skipped":
                            skipped += 1

                # Episodes (optional, --episodes)
                if movie.type == "show" and (args.episodes or (args.restore and done_eps.ids)):
                    eps = retry(movie.episodes, "episodes")
                    if args.dry_run and args.limit:  # keep previews manageable
                        per, eps_kept = {}, []
                        for ep in eps:
                            per[ep.parentIndex] = per.get(ep.parentIndex, 0) + 1
                            if per[ep.parentIndex] <= 2:
                                eps_kept.append(ep)
                        eps = eps_kept
                    ep_done = ep_skipped = 0
                    for ep in eps:
                        r = process_episode(movie, ep, args, server, backups, preview, done_eps)
                        if r == "done":
                            done += 1
                            ep_done += 1
                        elif r == "skipped":
                            skipped += 1
                            ep_skipped += 1
                    if ep_skipped and not ep_done and not args.restore:
                        print(f"      all {ep_skipped} episodes already done")
            except KeyboardInterrupt:
                print("\nStopped.")
                stopped = True
                break
            except Exception as e:
                print(f"[{i}/{len(movies)}] {movie.title}: failed after retries: {e}")
                failed += 1
                in_a_row += 1
                if in_a_row >= 3:
                    print("   Plex seems busy - pausing 2 minutes before continuing...")
                    time.sleep(120)
                    in_a_row = 0

    if stopped and REDO is None:
        print("Run the same command again to pick up where it left off.")
    if REDO is not None:
        if not stopped and failed == 0:
            REDO.clear()
            print("\nRedo finished.")
        else:
            print(
                "\nRedo not finished yet. Run the same command again, or pick 'Continue "
                "unfinished redo' in run.bat, to pick up where it stopped."
            )

    verb = "restored" if args.restore else ("previewed" if args.dry_run else "updated")
    print(f"\nDone. {done} {verb}, {skipped} skipped, {failed} failed.")
    if args.dry_run:
        print(f"Previews are in ./{preview}")


def main():
    p = argparse.ArgumentParser(
        description="Minimalist polaroid posters for Plex movies and TV shows"
    )
    p.add_argument("--url", default=os.getenv("PLEX_URL"), help="e.g. http://192.168.1.50:32400")
    p.add_argument("--token", default=os.getenv("PLEX_TOKEN"))
    p.add_argument(
        "--library",
        action="append",
        help="Plex library name; repeat for several, e.g. --library Movies "
        '--library "TV Shows" (default: Movies)',
    )
    p.add_argument("--dry-run", action="store_true", help="Make preview images only")
    p.add_argument("--limit", type=int, help="Only process the first N movies")
    p.add_argument("--force", action="store_true", help="Redo movies already labeled polaroid")
    p.add_argument("--restore", action="store_true", help="Put original posters back")
    p.add_argument("--only", help="Only movies whose title contains this text")
    p.add_argument(
        "--episodes",
        action="store_true",
        help="Also give every episode a wide polaroid thumbnail (slow on big libraries)",
    )
    p.add_argument(
        "--no-seasons",
        action="store_true",
        help="Only do the main show posters, not each season",
    )
    p.add_argument(
        "--use-still",
        action="store_true",
        help="Use a cropped film still instead of the whole poster",
    )
    p.add_argument(
        "--continue",
        dest="continue_redo",
        action="store_true",
        help="Continue an unfinished --force redo with the same libraries/options",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="With --force: ignore an unfinished redo and start the redo over",
    )
    p.add_argument("--backup-dir", default="poster_backups")
    args = p.parse_args()
    if not args.library:
        env = os.getenv("PLEX_LIBRARY", "Movies")
        args.library = [x.strip() for x in env.split(";") if x.strip()]

    if not args.url or not args.token:
        sys.exit("Need --url and --token (or PLEX_URL / PLEX_TOKEN env vars).")
    run(args)


if __name__ == "__main__":
    main()
