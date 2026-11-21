#!/usr/bin/env python3
# pyright: basic, reportOptionalMemberAccess=false, reportArgumentType=false
"""Serve the reconciliation app and send the emails a person approves.

Usage:
    python3 explorer/server.py            # http://localhost:8000/explorer/
    python3 explorer/server.py --port 8080

Nothing is sent automatically. An email goes out only when somebody presses Send in the UI.

Sending modes (picked at start-up, shown in the UI):
  agentmail AGENTMAIL_API_KEY and AGENTMAIL_INBOX are set: sent through the AgentMail API from that inbox.
  gmail     GMAIL_ADDRESS and GMAIL_APP_PASSWORD are set: sent through Gmail SMTP from that account.
            Create the app password at https://myaccount.google.com/apppasswords (needs 2-step verification).
  compose   No credentials: Send opens a pre-filled Gmail compose window in the browser.
  dry-run   MAIL_DRY_RUN=1: writes .eml files to data/outbox/ instead of sending (for demos and tests).

Settings are read from the environment, then from asklio/.env and the repo-root .env.
Edits and send status are kept in data/actions_state.json (gitignored).
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import http.server
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
import threading
import urllib.parse
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ACTIONS = HERE / "actions.json"
STATE = ROOT / "data" / "actions_state.json"
OUTBOX = ROOT / "data" / "outbox"
LOCK = threading.Lock()
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def load_env() -> None:
    for f in (ROOT / ".env", ROOT.parent / ".env"):
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
            if m and m.group(1) not in os.environ:
                os.environ[m.group(1)] = m.group(2).strip().strip("'\"")


load_env()
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
SENDER_NAME = os.environ.get("SENDER_NAME", "Procurement Operations")
AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "").strip()
AGENTMAIL_INBOX = os.environ.get("AGENTMAIL_INBOX", "").strip()
AGENTMAIL_API = "https://api.agentmail.to/v0"
MODE = ("dry-run" if os.environ.get("MAIL_DRY_RUN") == "1" else "agentmail" if AGENTMAIL_API_KEY and AGENTMAIL_INBOX
        else "gmail" if GMAIL_ADDRESS and GMAIL_APP_PASSWORD else "compose")


GMAIL_PROBLEM = ""


def gmail_connect() -> smtplib.SMTP_SSL:
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, local_hostname="localhost", context=ssl.create_default_context(), timeout=30)
    smtp.ehlo()
    try:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    except smtplib.SMTPServerDisconnected:
        # Gmail answers 535 to the first attempt and hangs up on smtplib's retry: that is a rejected password
        raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted") from None
    return smtp


class MailError(Exception):
    """The mail provider refused or could not be reached."""


def agentmail(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{AGENTMAIL_API}/inboxes/{urllib.parse.quote(AGENTMAIL_INBOX)}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {AGENTMAIL_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("message", "")
        except ValueError:
            detail = ""
        raise MailError(f"AgentMail answered {e.code}" + (f": {detail}" if detail else "")) from None
    except OSError as e:
        raise MailError(f"Could not reach AgentMail ({e})") from None


if MODE == "agentmail":  # same start-up check as for Gmail below
    try:
        agentmail("GET", "/messages?limit=1")
    except MailError as e:
        GMAIL_PROBLEM = f"{e}. Check AGENTMAIL_API_KEY and AGENTMAIL_INBOX."
        MODE = "compose"

if MODE == "gmail":  # check the credentials once, so a wrong password shows up at start-up and not on the first Send
    try:
        gmail_connect().quit()
    except smtplib.SMTPAuthenticationError:
        GMAIL_PROBLEM = (f"Gmail rejected the password for {GMAIL_ADDRESS}. It needs an app password "
                         "(myaccount.google.com/apppasswords), not the account password.")
        MODE = "compose"
    except (smtplib.SMTPException, OSError) as e:
        GMAIL_PROBLEM = f"Could not reach Gmail ({e}). Falling back to Gmail compose."
        MODE = "compose"


def read_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def merged() -> dict:
    """Drafts from actions.json with the person's edits and send status laid on top."""
    plan = read_json(ACTIONS, {"actions": [], "no_action": []})
    state = read_json(STATE, {})
    out = []
    for a in plan["actions"]:
        st = state.get(a["id"], {})
        a = {**a, "draft": {k: a[k] for k in ("to", "cc", "subject", "body")}}
        for k in ("to", "cc", "subject", "body"):
            if k in st:
                a[k] = st[k]
        a["status"] = st.get("status", "open")
        a["edited"] = any(a[k] != a["draft"][k] for k in ("to", "cc", "subject", "body"))
        a["history"] = st.get("history", [])
        out.append(a)
    return {"mode": MODE, "sender": AGENTMAIL_INBOX if MODE == "agentmail" else GMAIL_ADDRESS, "problem": GMAIL_PROBLEM, "sender_name": SENDER_NAME, "generated_at": plan.get("generated_at"),
            "actions": out, "no_action": plan.get("no_action", [])}


def update(aid: str, changes: dict, event: str | None = None) -> None:
    with LOCK:
        state = read_json(STATE, {})
        st = state.setdefault(aid, {})
        st.update(changes)
        if event:
            st.setdefault("history", []).append({"at": now(), "event": event})
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def split_addresses(text: str) -> list[str]:
    return [a.strip() for a in re.split(r"[,;]", text or "") if a.strip()]


def send_mail(fields: dict) -> dict:
    to, cc = split_addresses(fields.get("to", "")), split_addresses(fields.get("cc", ""))
    bad = [a for a in to + cc if not EMAIL_RE.match(a)]
    if not to:
        raise ValueError("Add a recipient address before sending.")
    if bad:
        raise ValueError("Not a valid email address: " + ", ".join(bad))
    if not fields.get("subject", "").strip() or not fields.get("body", "").strip():
        raise ValueError("Subject and body cannot be empty.")
    if MODE == "compose":
        url = "https://mail.google.com/mail/?" + urllib.parse.urlencode(
            {"view": "cm", "fs": "1", "to": ",".join(to), "cc": ",".join(cc), "su": fields["subject"], "body": fields["body"]})
        return {"via": "compose", "compose_url": url}
    if MODE == "agentmail":
        body = {"to": to, "subject": fields["subject"], "text": fields["body"],
                "html": "<div style=\"white-space:pre-wrap;font-family:sans-serif\">" + html.escape(fields["body"]) + "</div>"}
        if cc:
            body["cc"] = cc
        sent = agentmail("POST", "/messages/send", body)
        return {"via": "agentmail", "from": AGENTMAIL_INBOX, "message_id": sent.get("message_id"), "thread_id": sent.get("thread_id")}
    msg = EmailMessage()
    sender = GMAIL_ADDRESS or "dry-run@localhost"
    msg["From"] = formataddr((SENDER_NAME, sender))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = fields["subject"]
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(fields["body"])
    if MODE == "dry-run":
        OUTBOX.mkdir(parents=True, exist_ok=True)
        f = OUTBOX / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', fields['subject'].lower())[:40]}.eml"
        f.write_bytes(bytes(msg))
        return {"via": "dry-run", "file": f.relative_to(ROOT).as_posix(), "message_id": msg["Message-ID"]}
    with gmail_connect() as smtp:
        smtp.send_message(msg)
    return {"via": "gmail", "from": GMAIL_ADDRESS, "message_id": msg["Message-ID"]}


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet static-file noise, keep API calls
        if self.path.startswith("/api/"):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    def reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/actions":
            return self.reply(200, merged())
        if self.path in ("/", ""):
            self.send_response(302)
            self.send_header("Location", "/explorer/")
            return self.end_headers()
        return super().do_GET()

    def do_POST(self):
        m = re.fullmatch(r"/api/actions/([0-9a-f]{12})/(save|send|status)", self.path)
        if not m:
            return self.reply(404, {"error": "unknown endpoint"})
        aid, verb = m.groups()
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except json.JSONDecodeError:
            return self.reply(400, {"error": "invalid JSON"})
        action = next((a for a in merged()["actions"] if a["id"] == aid), None)
        if not action:
            return self.reply(404, {"error": "unknown action"})
        fields = {k: str(data[k]) for k in ("to", "cc", "subject", "body") if k in data}
        try:
            if verb == "save":
                update(aid, fields, "edited")
            elif verb == "status":
                status = data.get("status")
                if status not in ("open", "sent", "done", "dismissed"):
                    raise ValueError("unknown status")
                update(aid, {"status": status}, {"open": "reopened", "sent": "marked as sent", "done": "marked as resolved",
                                                 "dismissed": "dismissed"}[status])
            else:
                full = {**{k: action[k] for k in ("to", "cc", "subject", "body")}, **fields}
                result = send_mail(full)
                if result["via"] == "compose":
                    update(aid, fields, "opened in Gmail compose")
                else:
                    update(aid, {**fields, "status": "sent", "sent_at": now(), "sent_via": result["via"]},
                           f"sent via {result['via']} to {full['to']}")
                return self.reply(200, {"ok": True, **result, "action": next(a for a in merged()["actions"] if a["id"] == aid)})
        except ValueError as e:
            return self.reply(400, {"error": str(e)})
        except MailError as e:
            return self.reply(502, {"error": f"{e}. Nothing was sent."})
        except (smtplib.SMTPException, OSError) as e:
            return self.reply(502, {"error": f"Gmail did not accept the message: {e}"})
        return self.reply(200, {"ok": True, "action": next(a for a in merged()["actions"] if a["id"] == aid)})


def main() -> None:
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8000
    handler = functools.partial(Handler, directory=str(ROOT))
    desc = {"agentmail": f"sending through AgentMail as {AGENTMAIL_INBOX}", "gmail": f"sending through Gmail as {GMAIL_ADDRESS}", "compose": "no Gmail credentials: Send opens Gmail compose in the browser",
            "dry-run": "dry run: emails are written to data/outbox/"}[MODE]
    print(f"http://localhost:{port}/explorer/  ({desc})", flush=True)
    if GMAIL_PROBLEM:
        print("WARNING: " + GMAIL_PROBLEM, flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()


if __name__ == "__main__":
    main()
