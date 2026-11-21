"""Shared state between the agent, the folder watcher and the web UI.

One Hub holds the event log the UI renders, the approvals queue, and the inbox of
messages waiting to be injected into the running agent. Everything that reaches
the agent after start-up goes through `inject`: chat, new files, approval decisions.
All methods must be called from the event loop.
"""
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Approval:
    id: str
    tool: str  # send_email | edit_file | update_record
    args: dict
    headline: str
    reason: str
    evidence: list[str]
    severity: str  # blocker | risk | info
    status: str = "pending"  # pending | approved | rejected
    note: str = ""
    live: bool = False  # approving carries the action out, rather than only recording it
    outcome: str = ""  # done | failed | recorded, once approved
    result: str = ""
    thread_id: str = ""  # the mail conversation an approved email started or continued
    replies: list[dict] = field(default_factory=list)  # incoming messages in that conversation
    created: float = field(default_factory=time.time)
    decided: float | None = None


class Hub:
    def __init__(self, data_dir: Path, state_dir: Path):
        self.data_dir = data_dir
        self.state_dir = state_dir
        self.events: list[dict] = []
        self.approvals: dict[str, Approval] = {}
        self.inbox: list[str] = []
        self.wake = asyncio.Event()
        self.executors: dict = {}  # tool name -> async function(approval) -> result text; tools without one are only recorded
        self.mailbox = None
        self._subscribers: set[asyncio.Queue] = set()

    # ----- event log, streamed to the UI -----
    def emit(self, kind: str, **data) -> dict:
        event = {"seq": len(self.events) + 1, "ts": time.time(), "kind": kind, **data}
        self.events.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)
        return event

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    # ----- injections into the running agent -----
    def inject(self, text: str) -> None:
        self.inbox.append(text)
        self.wake.set()

    def drain(self) -> list[str]:
        texts, self.inbox = self.inbox, []
        return texts

    def chat(self, text: str) -> None:
        self.emit("user", text=text)
        self.inject(f"[chat] {text}")

    # ----- approvals -----
    def propose(self, tool: str, args: dict, headline: str, reason: str, evidence: list[str], severity: str) -> Approval:
        approval = Approval(f"A-{len(self.approvals) + 1}", tool, args, headline, reason, evidence, severity, live=tool in self.executors)
        self.approvals[approval.id] = approval
        self.emit("approval", approval=asdict(approval))
        return approval

    def attach_reply(self, thread_id: str, reply: dict) -> list[Approval]:
        """Link an incoming message to the approved emails of the same conversation, so the UI shows it there."""
        linked = [a for a in self.approvals.values() if thread_id and a.thread_id == thread_id]
        for approval in linked:
            approval.replies.append(reply)
            self.emit("approval", approval=asdict(approval))
        return linked

    async def decide(self, approval_id: str, approved: bool, note: str = "") -> Approval:
        approval = self.approvals[approval_id]
        if approval.status != "pending":
            raise ValueError(f"{approval_id} was already {approval.status}.")
        approval.status = "approved" if approved else "rejected"  # set before any await, so a second click cannot act twice
        approval.note = note.strip()
        approval.decided = time.time()
        note_text = f' Reviewer\'s note: "{approval.note}"' if approval.note else ""
        label = f"{approval.id} ({approval.tool}: {approval.headline})"
        if not approved:
            self.emit("approval", approval=asdict(approval))
            self.inject(f"[approval] {label} was REJECTED. It will not happen.{note_text}")
            return approval
        execute = self.executors.get(approval.tool)
        if execute is None:
            approval.outcome = "recorded"
            approval.result = "Recorded in the action log. This kind of action is not connected to an outside system yet."
            told = f"was APPROVED and recorded.{note_text} It is not connected to an outside system yet, so do not wait for an effect."
        else:
            try:
                approval.result = await execute(approval)
                approval.outcome = "done"
                told = f"was APPROVED and carried out. {approval.result}{note_text}"
            except Exception as err:
                approval.outcome = "failed"
                approval.result = f"{type(err).__name__}: {err}"
                told = f"was APPROVED but FAILED: {approval.result}.{note_text} Nothing went out. Fix the cause and propose it again if it is still needed."
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "actions.jsonl").open("a") as log:
            log.write(json.dumps(asdict(approval), ensure_ascii=False) + "\n")
        self.emit("approval", approval=asdict(approval))
        self.inject(f"[approval] {label} {told}")
        return approval
