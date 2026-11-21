# Soony reconciliation desk

The main screen is an **action inbox**: wherever the system and the evidence disagree, an email is drafted to the person who can confirm or fix it. You review it next to the ground truth, edit it if needed, and send it through Gmail. The data explorer (launch status, findings, parts, shipments, POs, goods receipts, suppliers, documents) sits behind it under "Ground truth".

## Run

The data is not in git. Get it first, from the repo root: `python3 scripts/update_data.py --apply` (see `data/README.md`).

```bash
cd asklio
python3 explorer/read_scans.py   # 1. read scanned delivery notes and contracts (Gemini on Vertex AI, cached)
python3 explorer/build.py        # 2. parse everything, compare paper vs ERP, derive findings -> data.json
python3 explorer/actions.py      # 3. plan and draft the emails per case (Gemini, cached) -> actions.json
python3 explorer/server.py       # 4. http://localhost:8000/explorer/
```

After a new data drop, install it with `scripts/update_data.py` (see `data/README.md`) and run steps 1 to 3 again. Only new or changed files and cases cost a model call.

## Sending email

Nothing is sent automatically: an email goes out only when somebody presses Send.

| Mode | When | What Send does |
|---|---|---|
| `agentmail` | `AGENTMAIL_API_KEY` and `AGENTMAIL_INBOX` are set (environment, `asklio/.env` or the repo-root `.env`) | Sends through the AgentMail API from that inbox. Takes precedence over Gmail. |
| `gmail` | `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` are set (environment or `asklio/.env`) | Sends through Gmail SMTP from that account. Create the app password at https://myaccount.google.com/apppasswords. |
| `compose` | no credentials | Opens a pre-filled Gmail compose window; you send it there and mark it as sent. |
| `dry-run` | `MAIL_DRY_RUN=1` | Writes `.eml` files to `data/outbox/`. For demos and tests. |

Suppliers only answer registered sender addresses: register the sender address (the AgentMail inbox or the Gmail address) in the Lio portal settings first.
How the team inbox works, and how to read replies: `notes/email.md`.
Internal Soony addresses are not in the data, so those drafts have an empty "To" until you add one.

## How it works

- `read_scans.py`: vision model reads each scan into structured lines (printed vs final quantity, pen corrections, stamps) and transcribes scanned contracts. Cached per file content in `data/extracted/`.
- `build.py`: stdlib parser for the ERP exports, spreadsheets and PDFs. Findings come from generic rules (paper vs booking, rejected inspections still in stock, receipts without PO, shortages vs bill of materials, late shipments, tracker vs ERP, order confirmation vs PO, expired conditional releases). Nothing is hardcoded to specific parts or suppliers.
- `actions.py`: groups findings into cases and lets the model decide who must be written to and draft the email in the recipient's language, using only facts from the case context. Supplier addresses must exist in the data or the field is left empty.
- `server.py`: serves the UI, keeps edits and status in `data/actions_state.json`, and sends approved emails.

Requirements: Python 3.10+, `gcloud` (logged in, project with Vertex AI), `pdftotext` (poppler). No pip packages.
`data.json`, `actions.json`, `data/extracted/`, `data/actions_state.json` and `data/outbox/` contain customer data and are gitignored.
