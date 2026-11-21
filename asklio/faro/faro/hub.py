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

from .store import Store


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
    needs_human: bool = True  # the agent's own call; anything it did not mark stays with a person
    human_reason: str = ""
    auto: bool = False  # approved by auto mode, not by a person
    created: float = field(default_factory=time.time)
    decided: float | None = None


class Hub:
    def __init__(self, data_dir: Path, state_dir: Path):
        self.data_dir = data_dir
        self.state_dir = state_dir
        self.events: list[dict] = []
        self.approvals: dict[str, Approval] = {}
        self.issues: dict[str, Issue] = {}
        self.auto = False  # auto mode: carry out proposals the agent marked as not needing a person
        self._auto_tasks: set = set()
        self.inbox: list[str] = []
        self.wake = asyncio.Event()
        self.executors: dict = {}  # tool name -> async function(approval) -> result text; tools without one are only recorded
        self.mailbox = None
        self.write_email = None  # async (to_name, language, brief, thread) -> {subject, body, translation}
        self._subscribers: set[asyncio.Queue] = set()
        self.translate_mail = None  # async (message_id, text) -> {language, summary, english}
        self.summarize = None  # async (text) -> one-line summary of a history entry
        self.emphasize = None  # async (text) -> the same words with bold and lists added
        self.store = Store(state_dir / "faro.db")
        if self.store.is_new:
            self.store.import_legacy(state_dir)  # carry over the JSON files from before the database existed
        self.events = self.store.events()
        self.issues = {i["id"]: Issue(**i) for i in self.store.issues()}
        self.approvals = {a["id"]: Approval(**a) for a in self.store.approvals()}
        self.auto = self.store.setting("auto", False)
        self.restored = bool(self.events)
        # Record changes approved before the ledger existed belong in it too.
        entered = {c["approval_id"] for c in self.store.corrections()}
        for approval in self.approvals.values():
            if approval.tool == "update_record" and approval.status == "approved" and approval.id not in entered:
                self._enter_corrections(approval)

    # ----- event log, streamed to the UI -----
    def emit(self, kind: str, **data) -> dict:
        event = {"seq": len(self.events) + 1, "ts": time.time(), "kind": kind, **data}
        self.events.append(event)
        self.store.add_event(event)
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
    def _show(self, issue: Issue) -> None:
        """Save an issue and tell the UI, with the corrections that belong to it."""
        issue.updated = time.time()
        self.store.put_issue(asdict(issue))
        self.emit("issue", issue=asdict(issue) | {"corrections": self.store.corrections(issue.id)})

    def _log(self, issue: Issue, kind: str, text: str, ref: str = "") -> None:
        entry = {"ts": time.time(), "kind": kind, "text": text, "ref": ref}
        issue.history.append(entry)
        self.store.add_history(issue.id, entry)
        self._show(issue)

    def _put(self, approval: Approval) -> None:
        self.store.put_approval(asdict(approval))
        self.emit("approval", approval=asdict(approval))

    def _enter_corrections(self, approval: Approval) -> None:
        changes = approval.args.get("changes") or []
        if isinstance(changes, dict):  # proposals from before the ledger carried only the new values
            changes = [{"field": k, "old_value": "", "new_value": v} for k, v in changes.items()]
        for change in changes:
            self.store.add_correction(approval.id, approval.issue_id, approval.args.get("system", ""), approval.args.get("record", ""), change["field"], change.get("old_value", ""), change["new_value"])

    def log_manual(self, issue_id: str, text: str) -> Issue:
        """Something that happened outside Faro and outside the mailbox: a call, a meeting, a decision someone took."""
        issue = self.issues[issue_id]
        self._log(issue, "logged", text.strip())
        self.inject(f"[log] The team recorded this on issue {issue.id} ({issue.title}): \"{text.strip()}\". It happened outside this system. Take it into account and update the issue if it changes anything.")
        return issue

    def mark_applied(self, correction_id: int, note: str = "") -> dict:
        correction = self.store.mark_applied(correction_id, note.strip())
        if correction is None:
            raise KeyError(correction_id)
        issue = self.issues[correction["issue_id"]]
        what = f"{correction['system']} · {correction['record']} · {correction['field']}: {correction['old_value'] or '?'} → {correction['new_value']}"
        self._log(issue, "applied", f"{what} is now changed in {correction['system']}." + (f" {note.strip()}" if note.strip() else ""), correction["approval_id"])
        self.inject(f"[log] The team has now made this correction in {correction['system']} itself: {what} (issue {issue.id}).")
        return correction

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
    def propose(self, tool: str, args: dict, issue_id: str, headline: str, reason: str, needs_human: bool = True, human_reason: str = "") -> Approval:
        approval = Approval(f"A-{len(self.approvals) + 1}", issue_id, tool, args, headline, reason, live=tool in self.executors,
                            needs_human=needs_human, human_reason=human_reason)
        self.approvals[approval.id] = approval
        self._put(approval)
        self._log(self.issues[issue_id], "proposed", headline, approval.id)
        self._run_auto()
        return approval

    def set_auto(self, on: bool) -> None:
        self.auto = on
        self.store.set_setting("auto", on)
        self.emit("auto", value=on)
        self._run_auto()

    def _run_auto(self) -> None:
        """In auto mode, carry out every waiting proposal the agent itself marked as not needing a person."""
        if not self.auto:
            return
        for approval in list(self.approvals.values()):
            if approval.status == "pending" and not approval.needs_human and approval.id not in {t.get_name() for t in self._auto_tasks}:
                task = asyncio.ensure_future(self.decide(approval.id, True, auto=True))
                task.set_name(approval.id)
                self._auto_tasks.add(task)
                task.add_done_callback(self._auto_tasks.discard)

    def attach_reply(self, thread_id: str) -> list[Issue]:
        """Count an incoming message on the issues its conversation belongs to, so the UI shows it there."""
        linked = [i for i in self.issues.values() if thread_id and thread_id in i.thread_ids]
        for issue in linked:
            issue.replies += 1
            self._show(issue)
        return linked

    async def decide(self, approval_id: str, approved: bool, note: str = "", auto: bool = False) -> Approval:
        approval = self.approvals[approval_id]
        issue = self.issues[approval.issue_id]
        if approval.status != "pending":
            raise ValueError(f"{approval_id} was already {approval.status}.")
        approval.status = "approved" if approved else "rejected"  # set before any await, so a second click cannot act twice
        approval.note = note.strip()
        approval.auto = auto
        approval.decided = time.time()
        by = "automatically, under auto mode, without a person reading it" if auto else "by the reviewer"
        note_text = f' Reviewer\'s note: "{approval.note}"' if approval.note else ""
        label = f"{approval.id} on issue {issue.id} ({approval.tool}: {approval.headline})"
        said = f" Note: {approval.note}" if approval.note else ""
        if not approved:
            self._put(approval)
            self._log(issue, "rejected", f"{approval.headline}.{said}", approval.id)
            self.inject(f"[approval] {label} was REJECTED. It will not happen.{note_text} Update the issue's next step.")
            return approval
        execute = self.executors.get(approval.tool)
        if approval.tool == "update_record":
            # No system is connected, so the decision goes into the corrections ledger: what the record should say, and since when.
            self._enter_corrections(approval)
            approval.outcome = "recorded"
            approval.result = f"Entered in the corrections ledger. It is not changed in {approval.args.get('system') or 'the system'} itself until someone does that there."
            told = f"was APPROVED {by} and entered in the corrections ledger.{note_text} Treat the corrected values as the truth from now on, although the exports still show the old ones. Nobody has changed {approval.args.get('system') or 'the system'} itself yet."
            kind = "auto_approved" if auto else "approved"
        elif execute is None:
            approval.outcome = "recorded"
            approval.result = "Recorded in the action log. This kind of action is not connected to an outside system yet."
            told = f"was APPROVED {by} and recorded.{note_text} It is not connected to an outside system yet, so do not wait for an effect."
            kind = "auto_approved" if auto else "approved"
        else:
            try:
                approval.result = await execute(approval)
                approval.outcome = "done"
                told = f"was APPROVED {by} and carried out. {approval.result}{note_text}"
                kind = "auto_sent" if auto else "sent"
                if approval.thread_id and approval.thread_id not in issue.thread_ids:
                    issue.thread_ids.append(approval.thread_id)
            except Exception as err:
                approval.outcome = "failed"
                approval.result = f"{type(err).__name__}: {err}"
                told = f"was APPROVED {by} but FAILED: {approval.result}.{note_text} Nothing went out. Fix the cause and propose it again if it is still needed."
                kind = "failed"
        self._put(approval)
        self._log(issue, kind, f"{approval.headline}.{said}" + (f" {approval.result}" if kind == "failed" else ""), approval.id)
        self.inject(f"[approval] {label} {told} Update the issue's next step.")
        return approval
