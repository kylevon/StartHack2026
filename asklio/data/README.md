# Soony data

**The data is not in git.** After cloning, check it out from the Soony portal:

```bash
python3 scripts/update_data.py --apply     # from the repo root; about 45 MB
```

The same command picks up new drops later. It needs `LIO_API_TOKEN` and `LIO_PROJECT_WEBSITE`, both in the repo-root `.env`.

| Path | What | In git |
|---|---|---|
| `CHANGELOG.md` | What changed in each snapshot and what it means. | yes |
| `soony-data/` | The current snapshot, extracted. The explorer reads this. | no |
| `soony-data.zip` | Local copy of the archive the snapshot came from. The script compares against it. | no |
| `extracted/`, `actions_state.json`, `outbox/` | Explorer caches and state. | no |

The portal always serves the complete current state, so each snapshot replaces the previous one. The portal keeps no history: an older snapshot cannot be downloaded again, only its description in `CHANGELOG.md` remains. (The 20 Nov and 21 Nov archives are still in git history up to the commit that removed the zip.)

## Getting new data

New files drop into the portal unannounced and existing files can be replaced. Nobody says what changed, so check a few times a day.

**1. Check** (from the repo root; downloads and changes nothing):

```bash
python3 scripts/update_data.py
```

It asks the portal API for the current file list and compares every SHA-256 against your local copy. It prints "Up to date", or the added, changed and removed files (exit code 10).

**2. Install:**

```bash
python3 scripts/update_data.py --apply
```

This downloads the archive, replaces `soony-data.zip`, re-extracts `soony-data/`, and adds a file-level entry to `CHANGELOG.md` unless that snapshot is already logged there (each entry carries a content fingerprint, so a teammate who syncs after you does not create a duplicate). It refuses if `soony-data/` has local edits that are not in the old zip (`--force` overrides).

The team token is `LIO_API_TOKEN` in the repo-root `.env` (from the portal's Settings page). Without API access, download the archive in the browser and pass it instead: `python3 scripts/update_data.py ~/Downloads/soony-data.zip --apply`.

**3. Review.** Read the new and changed files and replace the TODO under "What it means" in `CHANGELOG.md`.

**4. Refresh the explorer** (`cd asklio`): `read_scans.py`, `build.py`, `actions.py`, as in `explorer/README.md`. Only new or changed files cost a model call.

**5. Commit** `CHANGELOG.md`, so the team sees what changed. Teammates then run `--apply` themselves.

## Things to know

- Delta files (`master/bom_delta_*.csv`, `master/components_update_*.csv`) are not merged into `bom.csv` and `components.csv` by Soony. Apply them on top when reading master data.
- Column names can change between snapshots (`products.csv` did on 21 Nov).
