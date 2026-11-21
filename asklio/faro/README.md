# Faro

An agent that runs continuously over a folder of business documents, finds what is wrong or at risk, and asks a person before it changes anything.

Built on LangChain (`langchain.agents.create_agent`, the runtime LangGraph and deepagents share) and served locally with a three-part UI: approvals on the left, the selected decision in the centre, chat on the right.

## Run

```sh
cd asklio/faro
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> ../../.env.local   # untracked; do not put the key in .env, which is committed
uv run faro                                           # http://127.0.0.1:8000
```

No key yet? `FARO_MODEL=scripted uv run faro` runs a fixed script that reads one file and raises one sample approval, so the UI can be tried. It does not reason.

Point `FARO_DATA_DIR` at any folder of documents. The default is the hackathon data, unzipped at `asklio/data/soony-data/`.

`brief.md` is optional: a few plain sentences on whose documents these are and what matters to them. It is appended to the agent's instructions. Delete it or point `FARO_BRIEF` at another file to use the agent elsewhere; nothing else is specific to one customer.

| Variable | Default | |
|---|---|---|
| `FARO_MODEL` | `anthropic:claude-opus-5-5` | Any `init_chat_model` string, e.g. `anthropic:claude-sonnet-5-5` for a cheaper run |
| `FARO_DATA_DIR` | `asklio/data/soony-data` | Folder the agent reads and watches |
| `FARO_POLL_SECONDS` | `5` | How often the folder is checked for new files |
| `FARO_BRIEF` | `brief.md` | Optional description of this deployment |
| `FARO_COMPACT_TOKENS` | `150000` | Non-Claude models: history size at which old turns are summarised |
| `AGENTMAIL_INBOX`, `AGENTMAIL_API_KEY` | from the repo `.env` | Team mailbox. With both set, approved emails are really sent |
| `FARO_MAIL_MODEL` | `anthropic:claude-sonnet-5-5` | Model that writes the emails from the agent's brief |
| `FARO_MAIL` | `on` | `off` keeps email approvals record-only |
| `FARO_MAIL_POLL_SECONDS` | `20` | How often the mailbox is checked |
| `FARO_DATABASE_URL` | empty | Postgres URL (e.g. Supabase's session pooler) for the system of record. Empty: a local SQLite file |
| `FARO_PORT` | `8000` | |

## How it works

- **Files** (`files.py`): `list_files`, `search_files`, `read_file`, for any mix of types. Text and CSV in any common encoding, Excel (`.xlsx`, `.xlsm`, `.xls`) and PDF text come back as text. PDFs are read page by page, so scanned pages inside a text PDF are handed to the model as images, as are photos and scans (JPEG, PNG, TIFF, BMP, WebP, GIF), downscaled when too large. Long files come in parts rather than being cut. Search covers the text of PDFs and spreadsheets too. Paths cannot leave the folder.
- **Watching** (`agent.py: watch_folder`): the folder is polled; every new, changed or removed file is announced to the agent. Drop a file in and the agent picks it up.
- **Injection** (`hub.py`, `agent.py: InjectInbox`): chat messages, file announcements and approval decisions all go into one inbox. A middleware hands the inbox to the agent before every model call, so a message lands in the middle of whatever the agent is doing.
- **Issues** (`hub.py`, `tools.py`): the agent opens one issue per problem it finds (title, why it matters, evidence, next step) and keeps it current. Every proposal, email and note attaches to its issue, so the UI shows one card per problem with a Decision page (why, next action, evidence) and a History tab: one timeline of what the agent did, what the reviewer decided and the emails, read from the mailbox.
- **Approvals** (`tools.py`): `send_email`, `edit_file` and `update_record` never act when the agent calls them. Each call queues an approval on its issue and returns, so the agent keeps working; the decision is injected later.
- **Mail** (`mail.py`): the team's AgentMail inbox is the record of all outside communication. The agent is given the inbox's sent and received messages at start, checks it before proposing an email, and each proposal shows the reviewer what the inbox already holds with that recipient. The agent does not write emails: it gives a brief, and the mail model (Sonnet by default) drafts the message and an English translation. Approving sends it, or replies inside the thread. New incoming mail is injected as `[mail]`, marked as outside information and not as instructions, and linked to the approval it answers. The conversation shown in the UI is read from the inbox each time, not from Faro's memory. Recipients must be real addresses from the documents or from received mail. Scripted mode never sends.
- **Context** (`agent.py`): on Claude, server-side compaction replaces older turns, including old file contents, with a summary once the conversation passes about 150K tokens. Other providers get LangChain's `SummarizationMiddleware`, which does the same locally.

## System of record

Everything Faro itself knows and decided is in one database (`store.py`): a local SQLite file, `.faro/faro.db`, or a hosted Postgres when `FARO_DATABASE_URL` is set. On its first start against an empty hosted database Faro copies the local record across. With Postgres the tables live in their own `faro` schema, writes are queued to a background thread so the network never stalls the agent, and only one Faro should run per database, because the running instance assigns issue, approval and event numbers.

It holds:

- **Issues, approvals and history.** History is only ever added to: what the agent found and proposed, what was approved or rejected (by a person or by auto mode), and what the team logged by hand.
- **Corrections ledger.** An approved record change is stored as system, record, field, old value, new value and when it was approved. From then on the agent treats the new value as the truth (`list_corrections`), even though the export still shows the old one. "Mark as changed" records when someone has entered it in the system itself.
- **Manual log.** In an issue's History tab the team can record something that happened outside Faro and outside the mailbox: a call, a meeting, a decision. It is handed to the agent.
- **What has been seen.** The folder's file list and the handled mailbox messages, so a restart reports only what changed.
- **Derived text.** Translations, summaries and emphasis, so each is paid for once.

Kept outside on purpose: the emails (the mailbox is their source of truth; only links and derived text are stored), the documents (the data folder), secrets, and the agent's working memory.

## Not done yet

- **Only email is connected.** An approved `update_record` goes into the corrections ledger and an approved `edit_file` is recorded; neither changes the system or the file. The agent is told so.
- **Replies inside a thread are untested against the live mailbox.** New messages and reading are; the reply call follows AgentMail's documentation.
- **Files come from the local folder only.** To follow the Lio portal instead, sync its `GET /api/v1/files` into the folder, or replace `files.snapshot` and the reads.
- **The agent's working memory is not saved.** Everything else survives a restart (see System of record). After one, the agent is told which issues, proposals and corrections exist, hears only about files and mail that changed while it was down, and re-reads what it needs.
- **Claude's compaction is untested here.** It is configured as documented but has not run against the live API yet. The local summarisation path is covered by a test.
- **Word and PowerPoint files are not opened.**

## Tests

```sh
uv run pytest
```
