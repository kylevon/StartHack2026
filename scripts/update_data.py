#!/usr/bin/env python3
"""Sync the Soony portal data into the repo and show what changed.

The data is not in git. After cloning, run this script with --apply to get it.

The portal always serves the full current state, so a new snapshot replaces the
old one; nothing has to be merged. Files are compared by SHA-256.

Usage (from anywhere):
  python3 scripts/update_data.py            # ask the portal API what changed (downloads nothing)
  python3 scripts/update_data.py --apply    # download the archive and install it
  python3 scripts/update_data.py FILE.zip [--apply]   # same, from a zip downloaded by hand

The API needs LIO_API_TOKEN (team token from the portal's Settings page) and
LIO_PROJECT_WEBSITE in the environment or in the repo-root .env.

--apply does three things:
  1. replaces asklio/data/soony-data.zip (gitignored local copy) with the new archive,
  2. re-extracts asklio/data/soony-data/ (refused if that folder has local
     edits that are not in the old zip, unless --force),
  3. inserts a file-level entry at the top of asklio/data/CHANGELOG.md, unless
     that snapshot is already logged there (a teammate did it, or this is a
     fresh clone). Add by hand what the changes mean.

Exit code: 0 = up to date or installed, 10 = changes available but not installed.
Standard library only.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "asklio" / "data"
ZIP = DATA_DIR / "soony-data.zip"
EXTRACTED = DATA_DIR / "soony-data"
CHANGELOG = DATA_DIR / "CHANGELOG.md"
ENV_FILE = REPO / ".env"
MARKER = "<!-- new entries go below this line -->"


def load_env() -> dict:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            m = re.match(r'\s*(\w+)\s*=\s*"?(.*?)"?\s*$', line)
            if m:
                env[m.group(1)] = m.group(2)
    env.update(os.environ)
    return env


def api(path: str):
    env = load_env()
    token = env.get("LIO_API_TOKEN")
    base = env.get("LIO_PROJECT_WEBSITE", "")
    if not token or not base:
        sys.exit("The API needs LIO_API_TOKEN and LIO_PROJECT_WEBSITE (environment or .env).")
    base = base if "://" in base else "https://" + base
    url = "/".join(base.split("/")[:3]) + path
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        return urllib.request.urlopen(req, timeout=300)
    except urllib.error.HTTPError as e:
        sys.exit(f"Portal API returned {e.code} for {path}"
                 + (": check LIO_API_TOKEN." if e.code == 401 else "."))
    except urllib.error.URLError as e:
        sys.exit(f"Cannot reach the portal: {e.reason}")


def remote_index() -> dict:
    """{path: (sha256, size)} from the portal's file list."""
    with api("/api/v1/files") as r:
        files = json.load(r)["files"]
    return {f["path"]: (f["sha256"], f["bytes"]) for f in files}


def fetch(dest: Path) -> None:
    with api("/api/v1/archive.zip") as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_root(names: list[str]) -> str:
    """Return the single top-level folder all entries share, or ''."""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    return tops.pop() + "/" if len(tops) == 1 and all("/" in n for n in names) else ""


def zip_index(path: Path) -> dict:
    """{path without the top-level folder: (sha256, size)} for every file."""
    with zipfile.ZipFile(path) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        root = strip_root(names)
        return {n[len(root):]: (sha(z.read(n)), z.getinfo(n).file_size) for n in names}


def dir_index(path: Path) -> dict:
    return {
        p.relative_to(path).as_posix(): (sha(p.read_bytes()), p.stat().st_size)
        for p in sorted(path.rglob("*")) if p.is_file()
    }


def fingerprint(index: dict) -> str:
    """Identifies a snapshot by content, independent of how the zip was built."""
    return sha("\n".join(f"{k} {v[0]}" for k, v in sorted(index.items())).encode())[:16]


def diff(old: dict, new: dict):
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(old) & set(new) if old[k][0] != new[k][0])
    return added, removed, changed


def render(added, removed, changed, old, new) -> str:
    out = [
        f"## {dt.datetime.now():%Y-%m-%d %H:%M} snapshot",
        "",
        f"Snapshot `{fingerprint(new)}`, {len(new)} files "
        f"({len(added)} added, {len(changed)} changed, {len(removed)} removed).",
        "",
    ]
    for title, items in (("Added", added), ("Changed", changed), ("Removed", removed)):
        if not items:
            continue
        out.append(f"### {title}")
        for k in items:
            if title == "Changed":
                out.append(f"- `{k}` ({old[k][1]} → {new[k][1]} bytes)")
            else:
                out.append(f"- `{k}`")
        out.append("")
    out += ["### What it means", "- TODO: review the files above and write down the consequences.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="Diff and install a new Soony portal snapshot.")
    ap.add_argument("zip", nargs="?", help="a downloaded archive (default: ask the portal API)")
    ap.add_argument("--apply", action="store_true", help="install the snapshot and log it in CHANGELOG.md")
    ap.add_argument("--force", action="store_true", help="overwrite local edits in data/soony-data/")
    args = ap.parse_args()
    old = zip_index(ZIP) if ZIP.exists() else dir_index(EXTRACTED) if EXTRACTED.exists() else {}
    if not old:
        print("No local data yet: this will be a fresh checkout.\n")

    if not args.zip:
        # Cheap check first: the file list carries every SHA-256.
        new = remote_index()
        added, removed, changed = diff(old, new)
        if not (added or removed or changed):
            print(f"Up to date: {len(new)} files, same as {ZIP.relative_to(REPO)}.")
            return
        if not args.apply:
            print(render(added, removed, changed, old, new))
            print("Not installed. Re-run with --apply to download and install this snapshot.")
            sys.exit(10)

    with tempfile.TemporaryDirectory() as tmp:
        if args.zip:
            new_zip = Path(args.zip).expanduser()
        else:
            new_zip = Path(tmp) / "archive.zip"
            fetch(new_zip)
        if not zipfile.is_zipfile(new_zip):
            sys.exit(f"Not a zip file: {new_zip}")

        new = zip_index(new_zip)
        added, removed, changed = diff(old, new)
        entry = render(added, removed, changed, old, new)
        print(entry)

        if not (added or removed or changed):
            print("No changes: the repo already has this snapshot.")
            return
        if not args.apply:
            print("Not installed. Re-run with --apply to install this snapshot.")
            sys.exit(10)

        if EXTRACTED.exists():
            a, r, c = diff(old, dir_index(EXTRACTED))
            if (a or r or c) and not args.force:
                sys.exit(
                    f"{EXTRACTED} differs from the old zip ({len(a)} extra, {len(r)} missing, "
                    f"{len(c)} edited files). Nothing was changed. Use --force to overwrite."
                )
            shutil.rmtree(EXTRACTED)
        with zipfile.ZipFile(new_zip) as z:
            root = strip_root([i.filename for i in z.infolist() if not i.is_dir()])
            z.extractall(DATA_DIR if root else EXTRACTED)
        if root and root != EXTRACTED.name + "/":
            (DATA_DIR / root.rstrip("/")).rename(EXTRACTED)
        shutil.copyfile(new_zip, ZIP)

        text = CHANGELOG.read_text() if CHANGELOG.exists() else f"# Soony data changelog\n\n{MARKER}\n"
        if f"`{fingerprint(new)}`" in text:
            print(f"Installed. This snapshot is already described in {CHANGELOG.relative_to(REPO)}.")
        else:
            if MARKER not in text:
                text = text.rstrip() + f"\n\n{MARKER}\n"
            CHANGELOG.write_text(text.replace(MARKER, f"{MARKER}\n\n{entry.rstrip()}", 1).rstrip() + "\n")
            print(f"Installed. Now edit {CHANGELOG.relative_to(REPO)} and commit it.")
        print("Then re-run the explorer pipeline (asklio/explorer/README.md).")


if __name__ == "__main__":
    main()
