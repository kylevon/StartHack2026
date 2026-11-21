# StartHack 2026: Lio challenge "Keep the Line Running"

Team repo for the Soony case. The work is under `asklio/`. Task description: `asklio/task-description/description.md`.

## Where things are

| Need | Read |
|---|---|
| Get or update the Soony data (it is not in git) | `asklio/data/README.md`; run `python3 scripts/update_data.py --apply` from the repo root |
| What changed in each data drop, and what it means | `asklio/data/CHANGELOG.md` |
| Send or read email as the team | `asklio/notes/email.md` |
| Run the reconciliation app | `asklio/explorer/README.md` |
| Findings from the first data review | `asklio/notes/data-findings.md` |

## Rules

- **Email:** ask the human before sending to anyone outside the team. The full rules are at the top of `asklio/notes/email.md`.
- **Secrets:** credentials are in the repo-root `.env` and in `asklio/.env`. Never print them, and never copy them into other files, commit messages or outgoing mail.
- **Data:** `asklio/data/soony-data/` is a checkout managed by `scripts/update_data.py`. Do not edit files in it; the next sync refuses to overwrite local edits.
- **After a data drop:** review the new files and fill in the "What it means" section of the new changelog entry before committing it.
- **Master data deltas:** `master/bom_delta_*.csv` and `master/components_update_*.csv` are not merged into `bom.csv` and `components.csv`. Apply them on top when reading.
