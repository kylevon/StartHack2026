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

from . import adapters
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
    next_owner: str = ""  # who has to do that step
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
    status: str = "pending"  # pending | approved | rejected | withdrawn (by the agent, before anyone decided)
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
    def __init__(self, data_dir: Path, state_dir: Path, database_url: str = ""):
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
        self.store = Store(state_dir / "faro.db", database_url)
        if self.store.is_new:
            # Carry over what came before: the local database when moving to a hosted one, else the older JSON files.
            if not (database_url and self.store.import_sqlite(state_dir / "faro.db")):
                self.store.import_legacy(state_dir)
        self.events = self.store.events()
        self.issues = {i["id"]: Issue(**i) for i in self.store.issues()}
        self.approvals = {a["id"]: Approval(**a) for a in self.store.approvals()}
        self.auto = self.store.setting("auto", False)
        self.aggressive = self.store.setting("aggressive", False)  # negotiate hard; still only with facts
        self.objectives: list[str] = self.store.setting("objectives", [])  # what the team wants, most important first
        self.suppliers: list[dict] = self.store.setting("suppliers", [])  # the contact list the team and the agent share
        self.adapters_on: dict = self.store.setting("adapters", {})  # adapter id -> enabled: where approved corrections are posted
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

    def step_done(self, issue_id: str) -> Issue:
        """The team says the step that had to happen outside Faro has happened. Faro cannot see that for itself."""
        issue = self.issues[issue_id]
        if not issue.next_step:
            raise ValueError("This issue has no step waiting outside Faro.")
        step, who = issue.next_step, issue.next_owner
        issue.next_step, issue.next_owner = "", ""
        self._log(issue, "step_done", step)
        self.inject(f"[log] The team marked this step on issue {issue.id} ({issue.title}) as done{' by ' + who if who else ''}: \"{step}\". "
                    "Take it as having happened. Set a new next step only if something further is needed outside this system.")
        return issue

    def log_manual(self, issue_id: str, text: str) -> Issue:
        """Something that happened outside Faro and outside the mailbox: a call, a meeting, a decision someone took."""
        issue = self.issues[issue_id]
        self._log(issue, "logged", text.strip())
        self.inject(f"[log] The team recorded this on issue {issue.id} ({issue.title}): \"{text.strip()}\". It happened outside this system. Take it into account and update the issue if it changes anything.")
        return issue

    async def reconcile(self, correction_id: int, auto: bool = False) -> dict:
        """Post one ledger correction to its system through the enabled adapter, and record that in the issue's history."""
        correction = next((c for c in self.store.corrections() if c["id"] == correction_id), None)
        if correction is None:
            raise KeyError(correction_id)
        if correction["applied_at"]:
            raise ValueError("This correction is already in the system.")
        adapter = adapters.find(correction["system"], self.adapters_on)
        if adapter is None:
            raise ValueError(f"No adapter is enabled for {correction['system']}. Turn one on under Settings, Source of truth.")
        reference = await adapters.POSTERS[adapter.id](correction)
        how = f"Posted through the {adapter.name} adapter, reference {reference}."
        correction = self.store.mark_applied(correction_id, how)
        issue = self.issues[correction["issue_id"]]
        what = f"{correction['system']} · {correction['record']} · {correction['field']}: {correction['old_value'] or '?'} → {correction['new_value']}"
        self._log(issue, "auto_reconciled" if auto else "reconciled", f"{what}. {how}", correction["approval_id"])
        self.inject(f"[log] A correction was posted to {correction['system']}: {what} (issue {issue.id}). {how}")
        return correction

    def mark_applied(self, correction_id: int, note: str = "") -> dict:
        correction = self.store.mark_applied(correction_id, note.strip())
        if correction is None:
            raise KeyError(correction_id)
        issue = self.issues[correction["issue_id"]]
        what = f"{correction['system']} · {correction['record']} · {correction['field']}: {correction['old_value'] or '?'} → {correction['new_value']}"
        self._log(issue, "applied", f"{what} is now changed in {correction['system']}." + (f" {note.strip()}" if note.strip() else ""), correction["approval_id"])
        self.inject(f"[log] The team has now made this correction in {correction['system']} itself: {what} (issue {issue.id}).")
        return correction

    def open_issue(self, title: str, severity: str, summary: str, evidence: list[str], next_step: str = "", next_owner: str = "") -> Issue:
        issue = Issue(f"I-{len(self.issues) + 1}", title, severity, summary, evidence, next_step, next_owner if next_step else "")
        self.issues[issue.id] = issue
        self._log(issue, "found", summary)
        return issue

    def update_issue(self, issue_id: str, note: str, summary: str = "", next_step: str | None = None, status: str | None = None,
                     evidence: list[str] | None = None, thread_id: str = "", severity: str | None = None, next_owner: str | None = None) -> Issue:
        issue = self.issues[issue_id]
        if summary:
            issue.summary = summary
        if next_step is not None:
            issue.next_step = "" if next_step.strip().lower() in ("", "none") else next_step.strip()
            issue.next_owner = (next_owner or "").strip() if issue.next_step else ""
        elif next_owner is not None:
            issue.next_owner = next_owner.strip() if issue.next_step else ""
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
        live = tool in self.executors or (tool == "update_record" and adapters.find(args.get("system", ""), self.adapters_on) is not None)
        approval = Approval(f"A-{len(self.approvals) + 1}", issue_id, tool, args, headline, reason, live=live,
                            needs_human=needs_human, human_reason=human_reason)
        self.approvals[approval.id] = approval
        self._put(approval)
        self._log(self.issues[issue_id], "proposed", headline, approval.id)
        self._run_auto()
        return approval

    def set_auto(self, on: bool) -> None:
        self.update_settings(auto=on)

    # ----- settings the team controls -----
    def settings(self) -> dict:
        return {"auto": self.auto, "aggressive": self.aggressive, "objectives": self.objectives, "suppliers": self.suppliers,
                "adapters": [{"id": a.id, "name": a.name, "system": a.system, "description": a.description, "simulated": a.simulated, "enabled": bool(self.adapters_on.get(a.id))} for a in adapters.ADAPTERS]}

    def directives(self) -> str:
        """The team's standing instructions, as the agent is told them at start and whenever they change."""
        parts = []
        if self.objectives:
            parts.append("The team's objectives, most important first. Follow them in everything you decide and propose; when two conflict, the higher one wins:\n"
                         + "\n".join(f"  {n}. {text}" for n, text in enumerate(self.objectives, 1)))
        else:
            parts.append("The team has set no objectives. Use your own judgement about what matters most.")
        if self.aggressive:
            parts.append(
                "Aggressive mode is ON. The team has authorised you to be ruthless with suppliers on its behalf. Name every failure plainly, with its date and its "
                "number, and say who at the supplier owns it. Play suppliers against each other: where the documents or the mailbox show an alternative source, a "
                "second quote, spare stock or capacity elsewhere, say so and say the business will go there. Hold every contract clause against them: penalties, "
                "rush terms, service levels, the right to reject. Set deadlines in hours, not days, concede nothing without getting something back, and go over the "
                "contact's head to their management when a commitment slips. "
                "You may threaten the relationship itself. The team stands behind these consequences, so state them as its position: open purchase orders with this "
                "supplier will be reviewed and can be cancelled, they will be left out of future projects and tenders, volume will be moved to a competitor, and "
                "their supplier status will be downgraded. Tie the threat to something real where you can: an open order you have read, the next release, a "
                "contract renewal. Be cold and direct. Do not insult or demean anyone, and threaten commercial consequences only. "
                "What never changes is the truth about facts. State nothing as a fact that the documents or the mailbox do not support: never invent a competing "
                "offer, a price, a stock figure, a deadline or a decision already taken, and never deny or rewrite what was said before. A threat says what the "
                "team will do; it does not make up what has happened. Every email written this way needs a person, so mark it needs_human."
            )
        else:
            parts.append("Aggressive mode is off. Be firm and courteous with suppliers.")
        if self.suppliers:
            parts.append("The supplier list (the team may have corrected it; where it differs from the documents, the list is right):\n" + "\n".join(
                f"  {s.get('name', '?')} | contact {s.get('contact') or '-'} | {s.get('email') or 'no address'} | writes {s.get('language') or '?'}" + (f" | note: {s['notes']}" if s.get("notes") else "")
                for s in self.suppliers))
        else:
            parts.append("The supplier list is empty. Fill it with save_supplier from what the documents say about each supplier: name, contact person, email address, language.")
        on = [a for a in adapters.ADAPTERS if self.adapters_on.get(a.id)]
        if on:
            parts.append("Reconciliation is on for: " + ", ".join(f"{a.system} (through the {a.name} adapter)" for a in on)
                         + ". A correction to a record there is posted to the system as soon as it is approved, so propose corrections whenever a record is wrong.")
        else:
            parts.append("No system is connected for reconciliation. An approved correction only enters the ledger; someone has to change the system by hand.")
        return "\n\n".join(parts)

    def update_settings(self, auto: bool | None = None, aggressive: bool | None = None, objectives: list[str] | None = None, suppliers: list[dict] | None = None, by_agent: bool = False, adapters_on: dict | None = None) -> dict:
        tell = []
        if auto is not None and auto != self.auto:
            self.auto = auto
            self.store.set_setting("auto", auto)
        if aggressive is not None and aggressive != self.aggressive:
            self.aggressive = aggressive
            self.store.set_setting("aggressive", aggressive)
            tell.append("aggressive mode")
        if objectives is not None:
            cleaned = [text.strip() for text in objectives if text.strip()]
            if cleaned != self.objectives:
                self.objectives = cleaned
                self.store.set_setting("objectives", cleaned)
                tell.append("the objectives")
        if suppliers is not None and suppliers != self.suppliers:
            self.suppliers = suppliers
            self.store.set_setting("suppliers", suppliers)
            if not by_agent:
                tell.append("the supplier list")
        if adapters_on is not None:
            merged = self.adapters_on | {k: bool(v) for k, v in adapters_on.items() if any(a.id == k for a in adapters.ADAPTERS)}
            if merged != self.adapters_on:
                self.adapters_on = merged
                self.store.set_setting("adapters", merged)
                tell.append("which systems are connected for reconciliation")
        self.emit("settings", value=self.settings())
        if tell:
            self.inject(f"[settings] The team changed {' and '.join(tell)}. This replaces what you were told before:\n\n{self.directives()}")
        self._run_auto()
        return self.settings()

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

    def withdraw(self, approval_id: str, reason: str) -> Approval:
        """The agent takes back a proposal nobody has decided yet, because events overtook it."""
        approval = self.approvals[approval_id]
        if approval.status != "pending":
            raise ValueError(f"{approval_id} was already {approval.status}.")
        approval.status = "withdrawn"
        approval.note = reason.strip()
        approval.decided = time.time()
        self._put(approval)
        self._log(self.issues[approval.issue_id], "withdrawn", f"{approval.headline}. {reason.strip()}", approval.id)
        return approval

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
            system = approval.args.get("system") or "the system"
            approval.outcome = "recorded"
            kind = "auto_approved" if auto else "approved"
            if adapters.find(system, self.adapters_on):  # a connected system gets the correction straight away
                approval.result = f"Entered in the corrections ledger and posted to {system}."
                told = f"was APPROVED {by}, entered in the corrections ledger and posted to {system} through its adapter.{note_text} Treat the corrected values as the truth from now on, although the exports you read may still show the old ones."
                self._put(approval)
                self._log(issue, kind, f"{approval.headline}.{said}", approval.id)
                for correction in self.store.corrections(issue.id):
                    if correction["approval_id"] == approval.id and not correction["applied_at"]:
                        await self.reconcile(correction["id"], auto=True)
                self.inject(f"[approval] {label} {told} Update the issue's next step.")
                return approval
            approval.result = f"Entered in the corrections ledger. It is not changed in {system} itself until someone does that there."
            told = f"was APPROVED {by} and entered in the corrections ledger.{note_text} Treat the corrected values as the truth from now on, although the exports still show the old ones. Nobody has changed {system} itself yet."
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
