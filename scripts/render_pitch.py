#!/usr/bin/env python3
"""Render pitch.html to pitch/ so the deck can be read on GitHub.

GitHub shows HTML files as source, so this takes one screenshot per step of
the deck and writes pitch/README.md with the pictures and the speaker notes.
Run it from anywhere after changing pitch.html:

    python3 scripts/render_pitch.py

Needs chromium (or google-chrome) on the PATH.
"""
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "pitch.html"
OUT = ROOT / "pitch"

# Added to a temporary copy of the deck. "#dump" replaces the page with the
# list of steps as JSON; "#<n>" shows step n with the flip animation off.
HOOK = """
<script>
document.fonts.ready.then(() => {
  const steps = [];
  SLIDES.forEach((S, si) => S.steps.forEach((st, sti) => steps.push([si, sti])));
  const arg = location.hash.slice(1);
  if (arg === "dump") {
    const out = steps.map(([si, sti]) => {
      show(si, sti, false);
      return {
        slide: si + 1, step: sti + 1, of: SLIDES[si].steps.length,
        title: document.getElementById("title").textContent,
        caption: document.getElementById("cap").textContent,
        notes: SLIDES[si].notes,
      };
    });
    clearTimers();
    document.body.innerHTML = "<pre id='dump'></pre>";
    document.getElementById("dump").textContent = JSON.stringify(out);
  } else {
    const [si, sti] = steps[Number(arg)];
    show(si, sti, false);
  }
});
</script>
"""


def chromium():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("No chromium or google-chrome found on the PATH.")


def run(browser, profile, *args):
    cmd = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           f"--user-data-dir={profile}", "--virtual-time-budget=1500", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120).stdout


def main():
    browser = chromium()
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "deck.html"
        copy.write_text(DECK.read_text(encoding="utf-8").replace("</body>", HOOK + "</body>"), encoding="utf-8")
        profile = Path(tmp) / "profile"

        dom = run(browser, profile, "--dump-dom", f"{copy.as_uri()}#dump")
        found = re.search(r"<pre id=\"dump\">(.*?)</pre>", dom, re.S)
        if not found:
            sys.exit("The deck did not load: no step list came back.")
        steps = json.loads(html.unescape(found.group(1)))

        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir()
        for n, _ in enumerate(steps):
            png = OUT / f"step-{n + 1:02d}.png"
            run(browser, profile, "--window-size=1920,1080", f"--screenshot={png}", f"{copy.as_uri()}#{n}")
            print(png.relative_to(ROOT))

    lines = [
        "# Pitch deck",
        "",
        "Pictures of [`pitch.html`](../pitch.html), one per step, with the speaker notes. "
        "GitHub shows the HTML file as source, so this page is the way to read the deck here.",
        "",
        "To present it, open <https://kylevon.github.io/StartHack2026/>: "
        "arrow keys or click to advance, `F` fullscreen, `N` notes, `S` sound.",
        "",
        "This folder is generated. After changing the deck, run `python3 scripts/render_pitch.py`. "
        "The countdown in the corner shows the time left when the pictures were taken.",
        "",
    ]
    for n, s in enumerate(steps):
        if s["step"] == 1:
            lines += [f"## Slide {s['slide']}", ""]
        label = f"Slide {s['slide']}, step {s['step']} of {s['of']}: {s['title']}"
        lines += [f"![{label}](step-{n + 1:02d}.png)", ""]
        if s["step"] == s["of"]:
            lines += ["> " + s["notes"].replace("\n", " "), ""]
    (OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print((OUT / "README.md").relative_to(ROOT))


if __name__ == "__main__":
    main()
