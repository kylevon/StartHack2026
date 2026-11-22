"""Faro's system of record.

It holds everything Faro itself knows and decided: issues and their history,
approvals, the corrections ledger, the activity feed, settings, and what it has
already seen in the folder and the mailbox. History, the feed and the ledger are
only ever added to. Issues and approvals keep one current row each.

It lives in a local SQLite file by default, or in a hosted Postgres (such as
Supabase) when a database URL is given, so a team can share one record. One
running Faro per database: issue, approval and event numbers are assigned by the
running instance.

Two things stay outside on purpose: the emails (the mailbox is their source of
truth; only links and derived text are kept here) and the documents (the data
folder). The agent's working memory is not stored at all.
"""
import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Written once in a form both databases accept, apart from the two tokens replaced below.
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (seq BIGINT PRIMARY KEY, ts DOUBLE PRECISION NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, n BIGINT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS history (id {serial}, issue_id TEXT NOT NULL, ts DOUBLE PRECISION NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS history_issue ON history (issue_id, id);
CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, n BIGINT NOT NULL, issue_id TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corrections (
    id {serial}, approval_id TEXT NOT NULL, issue_id TEXT NOT NULL,
    system TEXT NOT NULL, record TEXT NOT NULL, field TEXT NOT NULL, old_value TEXT NOT NULL, new_value TEXT NOT NULL,
    approved_at DOUBLE PRECISION NOT NULL, applied_at DOUBLE PRECISION, applied_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cache (kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (kind, key));
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size BIGINT NOT NULL, mtime_ns BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS mail_seen (message_id TEXT PRIMARY KEY, seen_at DOUBLE PRECISION NOT NULL);
"""
TABLES = ["events", "issues", "history", "approvals", "corrections", "settings", "cache", "files", "mail_seen"]
PG_SCHEMA = "faro"  # its own schema, so the hosted database's public web API does not expose these tables


class _Sqlite:
    """The local file. Every call runs at once, in the caller's thread."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.where = str(path)
        self.is_new = not path.is_file()
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA.format(serial="INTEGER PRIMARY KEY AUTOINCREMENT"))
        self._db.commit()

    def write(self, sql: str, args=(), many: bool = False) -> None:
        (self._db.executemany if many else self._db.execute)(sql, args)
        self._db.commit()

    def read(self, sql: str, args=()) -> list[tuple]:
        rows = self._db.execute(sql, args).fetchall()
        self._db.commit()  # a statement with RETURNING writes too
        return rows

    def close(self) -> None:
        self._db.close()


class _Postgres:
    """A hosted database. Writes are queued to one background thread, in order, so a slow network
    never stalls the agent or the page; a read waits for the writes before it and then runs."""

    def __init__(self, url: str):
        import psycopg

        self._psycopg, self._url = psycopg, url
        self.where = url.split("@")[-1].split("?")[0]  # host and database, without the password
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="faro-db")
        self._db = None
        self.is_new = self._worker.submit(self._open).result()

    def _connect(self):
        self._db = self._psycopg.connect(self._url, autocommit=True, connect_timeout=15)
        self._db.execute(f"CREATE SCHEMA IF NOT EXISTS {PG_SCHEMA}")
        self._db.execute(f"SET search_path TO {PG_SCHEMA}")

    def _open(self) -> bool:
        self._connect()
        for statement in SCHEMA.format(serial="BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY").split(";"):
            if statement.strip():
                self._db.execute(statement)
        return self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0 and self._db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0

    def _do(self, sql: str, args, many: bool, fetch: bool):
        sql = sql.replace("?", "%s")
        for attempt in (1, 2):
            try:
                if many:
                    with self._db.cursor() as cursor:
                        cursor.executemany(sql, args)
                    return None
                cursor = self._db.execute(sql, args)
                return cursor.fetchall() if fetch else None
            except self._psycopg.OperationalError:  # the connection dropped: reconnect once and try again
                if attempt == 2:
                    raise
                self._connect()

    def write(self, sql: str, args=(), many: bool = False) -> None:
        def run():
            try:
                self._do(sql, args, many, False)
            except Exception as err:  # nobody is waiting for this result, so say it where it will be seen
                print(f"faro: a write to the database failed and was lost ({type(err).__name__}: {err})", file=sys.stderr)

        self._worker.submit(run)

    def read(self, sql: str, args=()) -> list[tuple]:
        return self._worker.submit(self._do, sql, args, False, True).result()

    def close(self) -> None:
        self._worker.submit(lambda: self._db and self._db.close()).result()
        self._worker.shutdown()


class Cache:
    """One kind of derived text (translations, summaries, emphasis), kept so it is paid for once."""

    def __init__(self, db, kind: str):
        self._db, self._kind = db, kind
        self._known: dict | None = None  # everything of this kind, read in one go at first use; one Faro runs per database, so nobody else adds to it

    def _all(self) -> dict:
        if self._known is None:
            self._known = {key: json.loads(value) for key, value in self._db.read("SELECT key, value FROM cache WHERE kind = ?", (self._kind,))}
        return self._known

    def get(self, key: str, default=None):
        return self._all().get(key, default)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def __getitem__(self, key: str):
        return self.get(key)

    def __setitem__(self, key: str, value) -> None:
        self._all()[key] = value
        self._db.write("INSERT INTO cache VALUES (?, ?, ?) ON CONFLICT (kind, key) DO UPDATE SET value = excluded.value", (self._kind, key, json.dumps(value, ensure_ascii=False)))


class Store:
    def __init__(self, path: Path, url: str = ""):
        self._db = _Postgres(url) if url else _Sqlite(path)
        self.where = self._db.where
        self.is_new = self._db.is_new
        self._caches: dict[str, Cache] = {}

    def close(self) -> None:
        self._db.close()

    def cache(self, kind: str) -> Cache:
        if kind not in self._caches:
            self._caches[kind] = Cache(self._db, kind)
        return self._caches[kind]

    # ----- the activity feed -----
    def add_event(self, event: dict) -> None:
        data = {k: v for k, v in event.items() if k not in ("seq", "ts", "kind")}
        self._db.write("INSERT INTO events VALUES (?, ?, ?, ?)", (event["seq"], event["ts"], event["kind"], json.dumps(data, ensure_ascii=False)))

    def events(self) -> list[dict]:
        return [{"seq": seq, "ts": ts, "kind": kind, **json.loads(data)} for seq, ts, kind, data in self._db.read("SELECT seq, ts, kind, data FROM events ORDER BY seq")]

    # ----- issues, their history, approvals -----
    def put_issue(self, issue: dict) -> None:
        body = {k: v for k, v in issue.items() if k != "history"}  # history has its own, append-only table
        self._db.write("INSERT INTO issues VALUES (?, ?, ?) ON CONFLICT (id) DO UPDATE SET data = excluded.data",
                       (issue["id"], int(issue["id"].split("-")[1]), json.dumps(body, ensure_ascii=False)))

    def add_history(self, issue_id: str, entry: dict) -> None:
        self._db.write("INSERT INTO history (issue_id, ts, kind, text, ref) VALUES (?, ?, ?, ?, ?)", (issue_id, entry["ts"], entry["kind"], entry["text"], entry.get("ref", "")))

    def issues(self) -> list[dict]:
        history: dict[str, list] = {}
        for issue_id, ts, kind, text, ref in self._db.read("SELECT issue_id, ts, kind, text, ref FROM history ORDER BY id"):
            history.setdefault(issue_id, []).append({"ts": ts, "kind": kind, "text": text, "ref": ref})
        return [json.loads(data) | {"history": history.get(issue_id, [])} for issue_id, data in self._db.read("SELECT id, data FROM issues ORDER BY n")]

    def put_approval(self, approval: dict) -> None:
        self._db.write("INSERT INTO approvals VALUES (?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET data = excluded.data",
                       (approval["id"], int(approval["id"].split("-")[1]), approval["issue_id"], json.dumps(approval, ensure_ascii=False)))

    def approvals(self) -> list[dict]:
        return [json.loads(data) for (data,) in self._db.read("SELECT data FROM approvals ORDER BY n")]

    # ----- the corrections ledger: what the team decided a system's record should say -----
    def add_correction(self, approval_id: str, issue_id: str, system: str, record: str, field: str, old_value: str, new_value: str) -> int:
        return self._db.read("INSERT INTO corrections (approval_id, issue_id, system, record, field, old_value, new_value, approved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                             (approval_id, issue_id, system, record, field, old_value, new_value, time.time()))[0][0]

    def mark_applied(self, correction_id: int, note: str) -> dict | None:
        self._db.write("UPDATE corrections SET applied_at = ?, applied_note = ? WHERE id = ? AND applied_at IS NULL", (time.time(), note, correction_id))
        return next((c for c in self.corrections() if c["id"] == correction_id), None)

    def corrections(self, issue_id: str | None = None) -> list[dict]:
        columns = ["id", "approval_id", "issue_id", "system", "record", "field", "old_value", "new_value", "approved_at", "applied_at", "applied_note"]
        where, args = (" WHERE issue_id = ?", (issue_id,)) if issue_id else ("", ())
        return [dict(zip(columns, row)) for row in self._db.read(f"SELECT {', '.join(columns)} FROM corrections{where} ORDER BY id", args)]

    # ----- settings and what has already been seen -----
    def setting(self, key: str, default=None):
        rows = self._db.read("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_setting(self, key: str, value) -> None:
        self._db.write("INSERT INTO settings VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))

    def known_files(self) -> dict[str, tuple[int, int]] | None:
        """The folder as it was last seen, or None if it was never looked at."""
        if not self.setting("folder_seen", False):
            return None
        return {path: (size, mtime) for path, size, mtime in self._db.read("SELECT path, size, mtime_ns FROM files")}

    def remember_files(self, snapshot: dict[str, tuple[int, int]]) -> None:
        self._db.write("DELETE FROM files")
        if snapshot:
            self._db.write("INSERT INTO files VALUES (?, ?, ?)", [(path, size, mtime) for path, (size, mtime) in snapshot.items()], many=True)
        self.set_setting("folder_seen", True)

    def seen_mail(self) -> set[str] | None:
        """Message ids already handled, or None if the mailbox was never looked at."""
        if not self.setting("mailbox_seen", False):
            return None
        return {message_id for (message_id,) in self._db.read("SELECT message_id FROM mail_seen")}

    def remember_mail(self, message_ids) -> None:
        rows = [(m, time.time()) for m in message_ids]
        if rows:
            self._db.write("INSERT INTO mail_seen VALUES (?, ?) ON CONFLICT (message_id) DO NOTHING", rows, many=True)
        self.set_setting("mailbox_seen", True)

    # ----- bringing an earlier record across, once -----
    def import_sqlite(self, path: Path) -> bool:
        """Copy a local SQLite record into this (empty) database, table by table."""
        if not path.is_file():
            return False
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for table in TABLES:
                columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                generated = table in ("history", "corrections")  # their ids are assigned by the database
                wanted = [c for c in columns if not (generated and c == "id")]
                rows = source.execute(f"SELECT {', '.join(wanted)} FROM {table}" + (" ORDER BY id" if generated else "")).fetchall()
                if rows:
                    self._db.write(f"INSERT INTO {table} ({', '.join(wanted)}) VALUES ({', '.join('?' * len(wanted))})", rows, many=True)
        finally:
            source.close()
        self._db.read("SELECT 1")  # wait until everything queued above is written
        return True

    def import_legacy(self, state_dir: Path) -> bool:
        """Read the JSON files Faro used before it had a database."""
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
