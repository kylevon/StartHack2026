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
| `FARO_MAIL` | `on` | `off` keeps email approvals record-only |
| `FARO_MAIL_POLL_SECONDS` | `20` | How often the mailbox is checked |
| `FARO_PORT` | `8000` | |

## How it works

- **Files** (`files.py`): `list_files`, `search_files`, `read_file`, for any mix of types. Text and CSV in any common encoding, Excel (`.xlsx`, `.xlsm`, `.xls`) and PDF text come back as text. PDFs are read page by page, so scanned pages inside a text PDF are handed to the model as images, as are photos and scans (JPEG, PNG, TIFF, BMP, WebP, GIF), downscaled when too large. Long files come in parts rather than being cut. Search covers the text of PDFs and spreadsheets too. Paths cannot leave the folder.
- **Watching** (`agent.py: watch_folder`): the folder is polled; every new, changed or removed file is announced to the agent. Drop a file in and the agent picks it up.
- **Injection** (`hub.py`, `agent.py: InjectInbox`): chat messages, file announcements and approval decisions all go into one inbox. A middleware hands the inbox to the agent before every model call, so a message lands in the middle of whatever the agent is doing.
- **Approvals** (`tools.py`): `send_email`, `edit_file` and `update_record` never act when the agent calls them. Each call queues an approval and returns, so the agent keeps working; the decision is injected later.
- **Mail** (`mail.py`): with the team's AgentMail inbox configured, approving a `send_email` proposal sends it (or replies inside the thread), and the result goes back to the agent. The inbox is polled; each new incoming message is injected as `[mail]`, marked as outside information and not as instructions. The agent can also `list_mail` and `read_mail`. Recipients must be real addresses from the documents or from received mail; a proposal with a made-up address is refused. Scripted mode never sends.
- **Context** (`agent.py`): on Claude, server-side compaction replaces older turns, including old file contents, with a summary once the conversation passes about 150K tokens. Other providers get LangChain's `SummarizationMiddleware`, which does the same locally.

## Not done yet

- **Only email is connected.** An approved `edit_file` or `update_record` is recorded in `.faro/actions.jsonl` and nothing else happens; the agent is told so. Every approved action, sent or not, is logged there.
- **Replies inside a thread are untested against the live mailbox.** New messages and reading are; the reply call follows AgentMail's documentation.
- **Files come from the local folder only.** To follow the Lio portal instead, sync its `GET /api/v1/files` into the folder, or replace `files.snapshot` and the reads.
- **State is in memory.** Restarting the server forgets the conversation and the approvals queue, and the agent starts its review again.
- **Claude's compaction is untested here.** It is configured as documented but has not run against the live API yet. The local summarisation path is covered by a test.
- **Word and PowerPoint files are not opened.**

## Tests

```sh
uv run pytest
```
