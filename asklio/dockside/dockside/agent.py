"""The continuously running agent and the folder watcher that feeds it."""
import asyncio
import re
from collections import Counter

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, SummarizationMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from . import config, files
from .hub import Hub
from .tools import READ_TOOLS, make_tools

SYSTEM_PROMPT = """You are Dockside, an autonomous agent that works for a team by watching a folder of their business documents: exports from their systems, PDFs, spreadsheets, scans, photos, notices, notes. What a system says and what the paper says often disagree, and nobody has had time to compare them. That comparison is your job: read what is there, work out what is wrong, missing or at risk, and get the right person to act before it costs something. If a section called "About this deployment" follows, it tells you whose documents these are and what matters to them; otherwise learn it from the folder itself, starting with anything that looks like notes, a readme or a plan.

You run continuously. You do not get one task and finish; messages reach you while you work, each tagged with where it came from:
- [files] The folder you watch has new, changed or removed files. Read what looks relevant and work out whether it changes anything you concluded.
- [chat] Someone on the team is talking to you through the app. Answer them directly and briefly, then carry on.
- [approval] A person decided on something you proposed.

Reading is free: list, search and read as much as you need. read_file opens text, CSV, Excel, PDF and image files; scanned pages and photos come back as images, so read them yourself, since a handwritten correction or a stamp is often the fact that matters. Anything that changes the world outside you is different. send_email, edit_file and update_record do not act when you call them. Each call puts a proposal in front of a person and returns an id straight away, so keep working on other things rather than waiting. The decision arrives later as an [approval] message. If a proposal is rejected, read the reviewer's note and change course; do not submit the same thing again unchanged.

The reviewer is busy and sees each proposal on its own, without your conversation. So make each one stand alone: a headline that states the problem with its number, a reason that says what you found, what it costs if ignored and why this action and this recipient, and the paths of the files you actually read as evidence. Raise one proposal per distinct problem, and before proposing, check you have not already raised it. Only propose what the documents support; if you are unsure, say what is uncertain in the reason, or ask in the email instead of asserting.

Write to each person in the language the documents show they use, and add an English translation for the reviewer when that is not English. Choose recipients from what the documents say about who owns or may decide what.

Earlier parts of your work may be summarised to save space. Trust the summary, and re-read a file when you need its exact wording again.

People watch your work as it happens. Before a group of tool calls, say in one short sentence what you are checking and why; skip it when the next action is obvious. When you write in chat, use plain text without markdown and get to the point in the first sentence: the answer first, then only the detail that changes what the reader does. When there is nothing useful left to do, stop. You will be woken when something new arrives."""


class InjectInbox(AgentMiddleware):
    """Before every model call, hand the agent whatever arrived since the last one.

    This is what makes chat, new files and approval decisions land in the middle
    of a running task instead of waiting for it to finish.
    """

    def __init__(self, hub: Hub):
        super().__init__()
        self.hub = hub

    async def abefore_model(self, state, runtime):
        texts = self.hub.drain()
        if texts:
            return {"messages": [HumanMessage("\n\n".join(texts))]}
        return None


def _text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content.strip()
    return "".join(b.get("text", "") for b in message.content if isinstance(b, dict) and b.get("type") == "text").strip()


def _thoughts(message: AIMessage) -> list[str]:
    """The model's own reasoning summaries, when the provider returns them."""
    if isinstance(message.content, str):
        return []
    found = []
    for block in message.content:
        if isinstance(block, dict) and block.get("type") in ("thinking", "reasoning"):
            text = (block.get("thinking") or block.get("reasoning") or "").strip()
            if text:
                found.append(text)
    return found


def _brief(text: str, limit: int = 150) -> str:
    """One quick line for the feed: whole leading sentences while they fit, else a cut at a word."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    line = ""
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        if len(line) + len(sentence) + 1 > limit:
            break
        line = f"{line} {sentence}".strip()
    return line or flat[:limit].rsplit(" ", 1)[0] + "…"


def _describe(call: dict) -> dict:
    """A tool call as a chip for the UI: a short label, and the full detail for the tooltip."""
    args = call["args"]
    if call["name"] == "read_file":
        path = args.get("path", "?")
        return {"verb": "Read", "label": path.rsplit("/", 1)[-1], "text": f"Read {path}"}
    if call["name"] == "search_files":
        query = args.get("query", "?")
        return {"verb": "Searched", "label": query, "text": f"Searched for \"{query}\" in {args.get('folder') or 'all files'}"}
    folder = args.get("folder") or "all files"
    return {"verb": "Listed", "label": folder.rstrip("/").rsplit("/", 1)[-1], "text": f"Listed {folder}"}


class AgentRunner:
    def __init__(self, hub: Hub, model):
        self.hub = hub
        middleware = [InjectInbox(hub)]
        if isinstance(model, str) and model.startswith("anthropic:"):
            # Claude compacts on its own servers: once the conversation passes ~150K tokens,
            # earlier turns (including old file contents) are replaced by a summary.
            model = init_chat_model(
                model,
                max_tokens=16000,
                thinking={"type": "adaptive", "display": "summarized"},  # so the UI can show what it thought
                betas=["compact-2026-01-12"],
                context_management={"edits": [{"type": "compact_20260112"}]},
            )
        else:
            if isinstance(model, str):
                model = init_chat_model(model, max_tokens=16000)
            # Other providers: summarise old turns locally once the history gets long.
            middleware.append(SummarizationMiddleware(model, trigger=("tokens", config.COMPACT_TOKENS), keep=("messages", 20)))
        prompt = SYSTEM_PROMPT
        if config.BRIEF:
            prompt += "\n\n# About this deployment\n\n" + config.BRIEF
        self.agent = create_agent(model, make_tools(hub), system_prompt=prompt, middleware=middleware, checkpointer=InMemorySaver())
        self.config = {"configurable": {"thread_id": "dockside"}, "recursion_limit": 10_000}

    async def run_forever(self) -> None:
        hub = self.hub
        while True:
            await hub.wake.wait()
            hub.wake.clear()
            if not hub.inbox:
                continue
            hub.emit("status", value="working")
            try:
                # No input here on purpose: InjectInbox delivers the inbox before the first model call.
                async for chunk in self.agent.astream({"messages": []}, self.config, stream_mode="updates"):
                    for update in chunk.values():
                        for message in (update or {}).get("messages", []):
                            self._show(message)
            except Exception as err:  # keep the loop alive: the next injection retries
                hub.emit("error", text=f"{type(err).__name__}: {err}")
            else:
                if hub.inbox:  # something arrived after the last model call
                    hub.wake.set()
            hub.emit("status", value="idle")

    def _show(self, message) -> None:
        if isinstance(message, AIMessage):
            for thought in _thoughts(message):
                self.hub.emit("thought", label=_brief(thought), text=thought)
            if text := _text(message):
                if message.tool_calls:  # said on the way to an action: a step, not a reply
                    self.hub.emit("step", label=_brief(text), text=text)
                else:
                    self.hub.emit("agent", text=text)
            for call in message.tool_calls:
                if call["name"] in READ_TOOLS:
                    self.hub.emit("activity", **_describe(call))
        elif isinstance(message, ToolMessage) and message.status == "error":
            self.hub.emit("activity", verb="Failed", label=message.name, text=f"{message.name} failed: {str(message.content)[:200]}")


def _layout(paths: list[str], depth: int = 3) -> str:
    counts = Counter("/".join(p.split("/")[:-1][:depth]) or "." for p in paths)
    return "\n".join(f"  {folder}/  {n} files" for folder, n in sorted(counts.items()))


def _listing(paths: list[str], limit: int = 60) -> str:
    shown = "\n".join(f"  {p}" for p in sorted(paths)[:limit])
    return shown + (f"\n  ... and {len(paths) - limit} more (use list_files)" if len(paths) > limit else "")


async def watch_folder(hub: Hub, poll_seconds: float) -> None:
    """Poll the document folder and tell the agent about every new or changed file."""
    known: dict | None = None
    while True:
        current = await asyncio.to_thread(files.snapshot, hub.data_dir)
        if known is None:
            if current:
                hub.emit("files", verb="Watching", label=f"{len(current)} files", text=f"Watching {hub.data_dir}: {len(current)} files")
                hub.inject(
                    f"[files] You are connected to the document folder. It holds {len(current)} files:\n"
                    f"{_layout(list(current))}\n"
                    "Start your review. New files will be announced as they arrive."
                )
            else:
                hub.emit("files", verb="Watching", label="empty folder", text=f"Watching {hub.data_dir}: no files yet")
        else:
            new = [p for p in current if p not in known]
            changed = [p for p in current if p in known and current[p] != known[p]]
            removed = [p for p in known if p not in current]
            if new or changed or removed:
                parts = []
                if new:
                    parts.append(f"{len(new)} new:\n{_listing(new)}")
                if changed:
                    parts.append(f"{len(changed)} changed:\n{_listing(changed)}")
                if removed:
                    parts.append(f"{len(removed)} removed:\n{_listing(removed)}")
                summary = ", ".join(f"{len(group)} {word}" for group, word in ((new, "new"), (changed, "changed"), (removed, "removed")) if group)
                hub.emit("files", verb="Files", label=summary, text="\n".join(sorted(new + changed + removed)[:40]))
                hub.inject("[files] The document folder changed.\n" + "\n".join(parts))
        known = current
        await asyncio.sleep(poll_seconds)
