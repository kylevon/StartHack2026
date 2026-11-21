# Dockside

An agent that runs continuously over a folder of business documents, finds what is wrong or at risk, and asks a person before it changes anything.

Built on LangChain (`langchain.agents.create_agent`, the runtime LangGraph and deepagents share) and served locally with a three-part UI: approvals on the left, the selected decision in the centre, chat on the right.

## Run

```sh
cd asklio/dockside
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> ../../.env.local   # untracked; do not put the key in .env, which is committed
uv run dockside                                           # http://127.0.0.1:8000
```

No key yet? `DOCKSIDE_MODEL=scripted uv run dockside` runs a fixed script that reads one file and raises one sample approval, so the UI can be tried. It does not reason.

Point `DOCKSIDE_DATA_DIR` at any folder of documents. The default is the hackathon data, unzipped at `asklio/data/soony-data/`.

`brief.md` is optional: a few plain sentences on whose documents these are and what matters to them. It is appended to the agent's instructions. Delete it or point `DOCKSIDE_BRIEF` at another file to use the agent elsewhere; nothing else is specific to one customer.

| Variable | Default | |
|---|---|---|
| `DOCKSIDE_MODEL` | `anthropic:claude-opus-5-5` | Any `init_chat_model` string, e.g. `anthropic:claude-sonnet-5-5` for a cheaper run |
| `DOCKSIDE_DATA_DIR` | `asklio/data/soony-data` | Folder the agent reads and watches |
| `DOCKSIDE_POLL_SECONDS` | `5` | How often the folder is checked for new files |
| `DOCKSIDE_BRIEF` | `brief.md` | Optional description of this deployment |
| `DOCKSIDE_COMPACT_TOKENS` | `150000` | Non-Claude models: history size at which old turns are summarised |
| `DOCKSIDE_PORT` | `8000` | |

## How it works

- **Files** (`files.py`): `list_files`, `search_files`, `read_file`, for any mix of types. Text and CSV in any common encoding, Excel (`.xlsx`, `.xlsm`, `.xls`) and PDF text come back as text. PDFs are read page by page, so scanned pages inside a text PDF are handed to the model as images, as are photos and scans (JPEG, PNG, TIFF, BMP, WebP, GIF), downscaled when too large. Long files come in parts rather than being cut. Search covers the text of PDFs and spreadsheets too. Paths cannot leave the folder.
- **Watching** (`agent.py: watch_folder`): the folder is polled; every new, changed or removed file is announced to the agent. Drop a file in and the agent picks it up.
- **Injection** (`hub.py`, `agent.py: InjectInbox`): chat messages, file announcements and approval decisions all go into one inbox. A middleware hands the inbox to the agent before every model call, so a message lands in the middle of whatever the agent is doing.
- **Approvals** (`tools.py`): `send_email`, `edit_file` and `update_record` never act when the agent calls them. Each call queues an approval and returns, so the agent keeps working; the decision is injected later.

- **Context** (`agent.py`): on Claude, server-side compaction replaces older turns, including old file contents, with a summary once the conversation passes about 150K tokens. Other providers get LangChain's `SummarizationMiddleware`, which does the same locally.

## Not done yet

- **Approved actions are only recorded**, in `.dockside/actions.jsonl`. No mail is sent, no file is edited, nothing is posted to any system. The agent is told this so it does not wait for replies.
- **Files come from the local folder only.** To follow the Lio portal instead, sync its `GET /api/v1/files` into the folder, or replace `files.snapshot` and the reads.
- **State is in memory.** Restarting the server forgets the conversation and the approvals queue, and the agent starts its review again.
- **Claude's compaction is untested here.** It is configured as documented but has not run against the live API yet. The local summarisation path is covered by a test.
- **Word and PowerPoint files are not opened.**

## Tests

```sh
uv run pytest
```
