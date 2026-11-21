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
class Issue:
    """One problem the agent found. Everything done about it hangs off it: proposals, mail, notes."""

    id: str
    title: str
    severity: str  # blocker | risk | info
    summary: str  # why it matters, kept current
    evidence: list[str]
    next_step: str = ""  # what has to happen next that no pending approval or awaited reply already covers; "" when nothing
    status: str = "open"  # open | resolved
    thread_ids: list[str] = field(default_factory=list)  # mail conversations that belong to this issue
    replies: int = 0  # incoming messages seen in those conversations; the messages are read from the mailbox
    history: list[dict] = field(default_factory=list)  # {ts, kind, text, ref}: what the agent and the reviewer did, in order
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)


@dataclass
class Approval:
    id: str
    issue_id: str
    tool: str  # send_email | edit_file | update_record
    args: dict
    headline: str  # the action, in a few words
    reason: str  # why this action
    status: str = "pending"  # pending | approved | rejected
    note: str = ""
    live: bool = False  # approving carries the action out, rather than only recording it
    outcome: str = ""  # done | failed | recorded, once approved
    result: str = ""
    thread_id: str = ""  # the mail conversation an approved email started or continued
    created: float = field(default_factory=time.time)
    decided: float | None = None


class Hub:
    def __init__(self, data_dir: Path, state_dir: Path):
        self.data_dir = data_dir
        self.state_dir = state_dir
        self.events: list[dict] = []
        self.approvals: dict[str, Approval] = {}
        self.issues: dict[str, Issue] = {}
        self.inbox: list[str] = []
        self.wake = asyncio.Event()
        self.executors: dict = {}  # tool name -> async function(approval) -> result text; tools without one are only recorded
        self.mailbox = None
        self.write_email = None  # async (to_name, language, brief, thread) -> {subject, body, translation}
        self._subscribers: set[asyncio.Queue] = set()
        self.translate_mail = None  # async (message_id, text) -> {language, english}
        self.restored = self._load()

    # ----- the event log and the approvals survive a restart; the agent's working memory does not -----
    @property
    def _state_file(self) -> Path:
        return self.state_dir / "state.json"

    def _load(self) -> bool:
        if not self._state_file.is_file():
            return False
        saved = json.loads(self._state_file.read_text())
        if "issues" not in saved:  # state from before issues existed cannot be mapped onto them
            self._state_file.replace(self.state_dir / "state-before-issues.json")
            return False
        self.events = saved["events"]
        self.issues = {i["id"]: Issue(**i) for i in saved["issues"]}
        self.approvals = {a["id"]: Approval(**a) for a in saved["approvals"]}
        return True

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        scratch = self._state_file.with_suffix(".tmp")
        scratch.write_text(json.dumps({"events": self.events, "issues": [asdict(i) for i in self.issues.values()], "approvals": [asdict(a) for a in self.approvals.values()]}, ensure_ascii=False))
        scratch.replace(self._state_file)

    # ----- event log, streamed to the UI -----
    def emit(self, kind: str, **data) -> dict:
        event = {"seq": len(self.events) + 1, "ts": time.time(), "kind": kind, **data}
        self.events.append(event)
        self.save()
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

    # ----- issues -----
    def _log(self, issue: Issue, kind: str, text: str, ref: str = "") -> None:
        issue.history.append({"ts": time.time(), "kind": kind, "text": text, "ref": ref})
        issue.updated = time.time()
        self.emit("issue", issue=asdict(issue))

    def open_issue(self, title: str, severity: str, summary: str, evidence: list[str], next_step: str = "") -> Issue:
        issue = Issue(f"I-{len(self.issues) + 1}", title, severity, summary, evidence, next_step)
        self.issues[issue.id] = issue
        self._log(issue, "found", summary)
        return issue

    def update_issue(self, issue_id: str, note: str, summary: str = "", next_step: str | None = None, status: str | None = None,
                     evidence: list[str] | None = None, thread_id: str = "", severity: str | None = None) -> Issue:
        issue = self.issues[issue_id]
        if summary:
            issue.summary = summary
        if next_step is not None:
            issue.next_step = "" if next_step.strip().lower() in ("", "none") else next_step.strip()
        if severity:
            issue.severity = severity
        for path in evidence or []:
            if path not in issue.evidence:
                issue.evidence.append(path)
        if thread_id and thread_id not in issue.thread_ids:
            issue.thread_ids.append(thread_id)
        kind = "note"
        if status and status != issue.status:
            issue.status = status
            kind = "resolved" if status == "resolved" else "reopened"
        self._log(issue, kind, note)
        return issue

    # ----- approvals -----
    def propose(self, tool: str, args: dict, issue_id: str, headline: str, reason: str) -> Approval:
        approval = Approval(f"A-{len(self.approvals) + 1}", issue_id, tool, args, headline, reason, live=tool in self.executors)
        self.approvals[approval.id] = approval
        self.emit("approval", approval=asdict(approval))
        self._log(self.issues[issue_id], "proposed", headline, approval.id)
        return approval

    def attach_reply(self, thread_id: str) -> list[Issue]:
        """Count an incoming message on the issues its conversation belongs to, so the UI shows it there."""
        linked = [i for i in self.issues.values() if thread_id and thread_id in i.thread_ids]
        for issue in linked:
            issue.replies += 1
            issue.updated = time.time()
            self.emit("issue", issue=asdict(issue))
        return linked

    async def decide(self, approval_id: str, approved: bool, note: str = "") -> Approval:
        approval = self.approvals[approval_id]
        issue = self.issues[approval.issue_id]
        if approval.status != "pending":
            raise ValueError(f"{approval_id} was already {approval.status}.")
        approval.status = "approved" if approved else "rejected"  # set before any await, so a second click cannot act twice
        approval.note = note.strip()
        approval.decided = time.time()
        note_text = f' Reviewer\'s note: "{approval.note}"' if approval.note else ""
        label = f"{approval.id} on issue {issue.id} ({approval.tool}: {approval.headline})"
        said = f" Note: {approval.note}" if approval.note else ""
        if not approved:
            self.emit("approval", approval=asdict(approval))
            self._log(issue, "rejected", f"{approval.headline}.{said}", approval.id)
            self.inject(f"[approval] {label} was REJECTED. It will not happen.{note_text} Update the issue's next step.")
            return approval
        execute = self.executors.get(approval.tool)
        if execute is None:
            approval.outcome = "recorded"
            approval.result = "Recorded in the action log. This kind of action is not connected to an outside system yet."
            told = f"was APPROVED and recorded.{note_text} It is not connected to an outside system yet, so do not wait for an effect."
            kind = "approved"
        else:
            try:
                approval.result = await execute(approval)
                approval.outcome = "done"
                told = f"was APPROVED and carried out. {approval.result}{note_text}"
                kind = "sent"
                if approval.thread_id and approval.thread_id not in issue.thread_ids:
                    issue.thread_ids.append(approval.thread_id)
            except Exception as err:
                approval.outcome = "failed"
                approval.result = f"{type(err).__name__}: {err}"
                told = f"was APPROVED but FAILED: {approval.result}.{note_text} Nothing went out. Fix the cause and propose it again if it is still needed."
                kind = "failed"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with (self.state_dir / "actions.jsonl").open("a") as log:
            log.write(json.dumps(asdict(approval), ensure_ascii=False) + "\n")
        self.emit("approval", approval=asdict(approval))
        self._log(issue, kind, f"{approval.headline}.{said}" + (f" {approval.result}" if kind == "failed" else ""), approval.id)
        self.inject(f"[approval] {label} {told} Update the issue's next step.")
        return approval
