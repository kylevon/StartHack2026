# StartHack 2026: Faro

Our entry for the Lio challenge "Keep the Line Running" (task: `asklio/task-description/`).

**Faro** is an agent for procurement teams. It reads a company's documents and its supplier mailbox continuously, finds where the system of record and reality disagree, and prepares the fix: an email to a supplier in their language, or a correction to a record. Nothing leaves without a person's approval.

On the Soony case it found that the launch plan marked parts "ok" that were not: art books booked ten times too high, a failed statue lot booked as usable, a container of cases waiting at the port, and a magnet shortage that was a false alarm. Each finding comes with the documents that prove it.

## What is in it

- **Issues**, ranked by urgency, each with why it matters, the next action, the evidence, and a history of everything done about it.
- **Approvals** for every email and every change to a record. Auto mode can release the ones that need no human.
- **Could go wrong**: problems anticipated before they happen, each with a measure to prevent it.
- **Mail** through a real inbox, written in the supplier's language and translated for the team.
- **A corrections ledger** and connectors to post approved corrections to the system of record (the SAP connector is a stand-in).
- **Settings** for ranked objectives, suppliers, connections and automation.

Code, architecture and configuration: [`asklio/faro/README.md`](asklio/faro/README.md).

## Run it

```sh
python3 scripts/update_data.py --apply      # the Soony data is not in git; this fetches it (see asklio/data/README.md)
cd asklio/faro
uv run faro                                 # http://127.0.0.1:8000
```

The agent needs an Anthropic API key in an untracked `.env.local` at the repo root (`ANTHROPIC_API_KEY=...`). Without one:

- `FARO_MODEL=off uv run faro` serves the saved record with no agent.
- `FARO_MODEL=scripted uv run faro` runs a fixed script so the interface can be tried; see the Faro README for running it against a separate state.

Tests: `cd asklio/faro && uv run pytest`.

## Elsewhere in the repo

| Path | What |
|---|---|
| `asklio/faro/` | Faro |
| `asklio/explorer/` | The earlier reconciliation app |
| `asklio/data/` | Data sync notes and the changelog of each data drop |
| `asklio/notes/` | Data findings and the rules for the team mailbox |
| `results/` | Log export and chart data for the pitch |
| `CLAUDE.md` | Start here if you are a coding agent |
