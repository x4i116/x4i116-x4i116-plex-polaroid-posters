#!/usr/bin/env python3
"""
cw_check.py - Find out exactly which image Plex serves for each item in
Continue Watching.

Run it from this folder (it reads your settings.bat, so run run.bat once first):
    py cw_check.py

For every Continue Watching item it downloads every image Plex could use
for it - the show poster, the season poster, the episode thumbnail - two
ways:
  - "direct":     the image file itself
  - "resized":    the smaller copy the Plex server makes for apps
                  (this is what the Continue Watching row actually loads)
Everything goes into a "cw_check" folder, and the addresses are printed.
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from plexapi.server import PlexServer

here = Path(__file__).resolve().parent
settings = {}
sfile = here / "settings.bat"
if not sfile.exists():
    sys.exit("Can't find settings.bat - put this file in the same folder as run.bat.")
for line in sfile.read_text(encoding="utf-8", errors="replace").splitlines():
    m = re.match(r'\s*set\s+"([A-Z_]+)=(.*)"\s*$', line, re.I)
    if m:
        settings[m.group(1).upper()] = m.group(2)

server = PlexServer(settings["PLEX_URL"], settings["PLEX_TOKEN"], timeout=60)

# The Continue Watching row, exactly as Plex builds it
try:
    items = server.fetchItems("/hubs/continueWatching/items")
except Exception:
    items = server.library.onDeck()
if not items:
    sys.exit("Plex says Continue Watching is empty.")

out = here / "cw_check"
out.mkdir(exist_ok=True)
for f in out.glob("*.jpg"):
    f.unlink()


def save(url, name):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return f"error {r.status_code}"
        (out / name).write_bytes(r.content)
        return "saved"
    except Exception as e:
        return f"failed ({e})"


def clean(text):
    return "".join(c for c in str(text) if c.isalnum() or c in " -_()").strip()


for it in items:
    show = getattr(it, "grandparentTitle", None) or it.title
    label = show
    if getattr(it, "type", "") == "episode":
        label = f"{show} S{it.parentIndex}E{it.index}"
    print(f"\n=== {label} ===")
    fields = [
        ("show poster", getattr(it, "grandparentThumb", None)),
        ("season poster", getattr(it, "parentThumb", None)),
        ("episode or item image", getattr(it, "thumb", None)),
    ]
    for what, path in fields:
        if not path:
            print(f"  {what:22} (none)")
            continue
        direct = server.url(path, includeToken=True)
        resized = server.url(
            f"/photo/:/transcode?width=300&height=450&minSize=1&upscale=1&url={quote(path)}",
            includeToken=True,
        )
        base = f"{clean(label)} - {what}"
        r1 = save(direct, f"{base} - direct.jpg")
        r2 = save(resized, f"{base} - resized.jpg")
        print(f"  {what:22} {path}")
        print(f"  {'':22} direct: {r1}   resized: {r2}")

print(f"\nDone. Open the '{out.name}' folder and look at the images for the show that's wrong.")
