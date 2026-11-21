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
        approval = Approval(f"A-{len(self.approvals) + 1}", tool, args, headline, reason, evidence, severity)
        self.approvals[approval.id] = approval
        self.emit("approval", approval=asdict(approval))
        return approval

    def decide(self, approval_id: str, approved: bool, note: str = "") -> Approval:
        approval = self.approvals[approval_id]
        if approval.status != "pending":
            raise ValueError(f"{approval_id} was already {approval.status}.")
        approval.status = "approved" if approved else "rejected"
        approval.note = note.strip()
        approval.decided = time.time()
        self.emit("approval", approval=asdict(approval))
        note_text = f' Reviewer\'s note: "{approval.note}"' if approval.note else ""
        if approved:
            # Nothing is wired to a real mailbox, file or ERP yet: an approved action is only recorded.
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with (self.state_dir / "actions.jsonl").open("a") as log:
                log.write(json.dumps(asdict(approval), ensure_ascii=False) + "\n")
            self.inject(
                f"[approval] {approval.id} ({approval.tool}: {approval.headline}) was APPROVED and recorded in the action log."
                f"{note_text} Delivery to the outside system is not connected yet, so do not wait for an effect or a reply."
            )
        else:
            self.inject(f"[approval] {approval.id} ({approval.tool}: {approval.headline}) was REJECTED. It will not happen.{note_text}")
        return approval
