"""Faro's system of record: one small SQLite file.

It holds everything Faro itself knows and decided: issues and their history,
approvals, the corrections ledger, the activity feed, settings, and what it has
already seen in the folder and the mailbox. History, the feed and the ledger are
only ever added to. Issues and approvals keep one current row each.

Two things stay outside on purpose: the emails (the mailbox is their source of
truth; only links and derived text are kept here) and the documents (the data
folder). The agent's working memory is not stored at all.
"""
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, n INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS history_issue ON history (issue_id, id);
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, n INTEGER NOT NULL, issue_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT, approval_id TEXT NOT NULL, issue_id TEXT NOT NULL,
    system TEXT NOT NULL, record TEXT NOT NULL, field TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
    approved_at REAL NOT NULL, applied_at REAL, applied_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cache (kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS mail_seen (message_id TEXT PRIMARY KEY, seen_at REAL NOT NULL);
"""


class Cache:
    """One kind of derived text (translations, summaries, emphasis), kept so it is paid for once."""

    def __init__(self, db: sqlite3.Connection, kind: str):
        self._db, self._kind = db, kind

    def get(self, key: str, default=None):
        row = self._db.execute("SELECT value FROM cache WHERE kind = ? AND key = ?", (self._kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key: str):
        return self.get(key)

    def __setitem__(self, key: str, value) -> None:
        self._db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (self._kind, key, json.dumps(value, ensure_ascii=False)))
        self._db.commit()


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.is_new = not path.is_file()
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def _run(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        cursor = self._db.execute(sql, args)
        self._db.commit()
        return cursor

    def cache(self, kind: str) -> Cache:
        return Cache(self._db, kind)

    # ----- the activity feed -----
    def add_event(self, event: dict) -> None:
        data = {k: v for k, v in event.items() if k not in ("seq", "ts", "kind")}
        self._run("INSERT INTO events VALUES (?, ?, ?, ?)", (event["seq"], event["ts"], event["kind"], json.dumps(data, ensure_ascii=False)))

    def events(self) -> list[dict]:
        return [{"seq": seq, "ts": ts, "kind": kind, **json.loads(data)} for seq, ts, kind, data in self._db.execute("SELECT seq, ts, kind, data FROM events ORDER BY seq")]

    # ----- issues, their history, approvals -----
    def put_issue(self, issue: dict) -> None:
        body = {k: v for k, v in issue.items() if k != "history"}  # history has its own, append-only table
        self._run("INSERT OR REPLACE INTO issues VALUES (?, ?, ?)", (issue["id"], int(issue["id"].split("-")[1]), json.dumps(body, ensure_ascii=False)))

    def add_history(self, issue_id: str, entry: dict) -> None:
        self._run("INSERT INTO history (issue_id, ts, kind, text, ref) VALUES (?, ?, ?, ?, ?)", (issue_id, entry["ts"], entry["kind"], entry["text"], entry.get("ref", "")))

    def issues(self) -> list[dict]:
        out = []
        for (data,) in self._db.execute("SELECT data FROM issues ORDER BY n"):
            issue = json.loads(data)
            issue["history"] = [{"ts": ts, "kind": kind, "text": text, "ref": ref} for ts, kind, text, ref in
                                self._db.execute("SELECT ts, kind, text, ref FROM history WHERE issue_id = ? ORDER BY id", (issue["id"],))]
            out.append(issue)
        return out

    def put_approval(self, approval: dict) -> None:
        self._run("INSERT OR REPLACE INTO approvals VALUES (?, ?, ?, ?)", (approval["id"], int(approval["id"].split("-")[1]), approval["issue_id"], json.dumps(approval, ensure_ascii=False)))

    def approvals(self) -> list[dict]:
        return [json.loads(data) for (data,) in self._db.execute("SELECT data FROM approvals ORDER BY n")]

    # ----- the corrections ledger: what the team decided a system's record should say -----
    def add_correction(self, approval_id: str, issue_id: str, system: str, record: str, field: str, old_value: str, new_value: str) -> int:
        return self._run("INSERT INTO corrections (approval_id, issue_id, system, record, field, old_value, new_value, approved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (approval_id, issue_id, system, record, field, old_value, new_value, time.time())).lastrowid

    def mark_applied(self, correction_id: int, note: str) -> dict | None:
        self._run("UPDATE corrections SET applied_at = ?, applied_note = ? WHERE id = ? AND applied_at IS NULL", (time.time(), note, correction_id))
        return next((c for c in self.corrections() if c["id"] == correction_id), None)

    def corrections(self, issue_id: str | None = None) -> list[dict]:
        columns = ["id", "approval_id", "issue_id", "system", "record", "field", "old_value", "new_value", "approved_at", "applied_at", "applied_note"]
        where, args = (" WHERE issue_id = ?", (issue_id,)) if issue_id else ("", ())
        return [dict(zip(columns, row)) for row in self._db.execute(f"SELECT {', '.join(columns)} FROM corrections{where} ORDER BY id", args)]

    # ----- settings and what has already been seen -----
    def setting(self, key: str, default=None):
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        self._run("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, json.dumps(value)))

    def known_files(self) -> dict[str, tuple[int, int]] | None:
        """The folder as it was last seen, or None if it was never looked at."""
        if not self.setting("folder_seen", False):
            return None
        return {path: (size, mtime) for path, size, mtime in self._db.execute("SELECT path, size, mtime_ns FROM files")}

    def remember_files(self, snapshot: dict[str, tuple[int, int]]) -> None:
        self._db.execute("DELETE FROM files")
        self._db.executemany("INSERT INTO files VALUES (?, ?, ?)", [(path, size, mtime) for path, (size, mtime) in snapshot.items()])
        self._db.commit()
        self.set_setting("folder_seen", True)

    def seen_mail(self) -> set[str] | None:
        """Message ids already handled, or None if the mailbox was never looked at."""
        if not self.setting("mailbox_seen", False):
            return None
        return {message_id for (message_id,) in self._db.execute("SELECT message_id FROM mail_seen")}

    def remember_mail(self, message_ids) -> None:
        self._db.executemany("INSERT OR IGNORE INTO mail_seen VALUES (?, ?)", [(m, time.time()) for m in message_ids])
        self._db.commit()
        self.set_setting("mailbox_seen", True)

    # ----- one-time import of the JSON files that came before this database -----
    def import_legacy(self, state_dir: Path) -> bool:
        state = state_dir / "state.json"
        if not state.is_file():
            return False
        saved = json.loads(state.read_text())
        if "issues" not in saved:
            return False
        for event in saved["events"]:
            self.add_event(event)
        for issue in saved["issues"]:
            self.put_issue(issue)
            for entry in issue.get("history", []):
                self.add_history(issue["id"], entry)
        for approval in saved["approvals"]:
            self.put_approval(approval)
        self.set_setting("auto", saved.get("auto", False))
        for kind, name in (("translations", "translations.json"), ("summaries", "summaries.json"), ("emphasis", "emphasis.json")):
            if (state_dir / name).is_file():
                cache = self.cache(kind)
                for key, value in json.loads((state_dir / name).read_text()).items():
                    cache[key] = value
        state.replace(state_dir / "state-imported-into-faro-db.json")
        return True
