#!/usr/bin/env python3
"""
world_db.py — the world engine's store, and the contract every engine module keeps.

Opt-in per campaign: `world_engine: on` in state.md → ## Session Flags. With the flag off nothing
here runs and no file is created; the campaign plays exactly as before.

THE CONTRACT (read this before adding an engine module)

Store      <campaign>/world.db, SQLite from the standard library. It is in turn_snapshot's file
           set, so /dne undo restores it with the turn.
Writer     One writer per campaign: every change happens inside `with writer(campaign) as db:`
           (BEGIN IMMEDIATE). No engine module opens the file any other way.
Tables     inputs    what the table sent, stored before it is acknowledged (unique input_id)
           turns     one per input; status open | finished | abandoned
           actions   the intents of a turn, in order; status pending | applying | waiting | done | cancelled
           rolls     one result per (action, key): a retry reads it, it never rolls again
           requests  questions and roll requests waiting on a player (request_id, expected, epoch)
           outbox    messages to deliver; a fixed message_id lets the display drop a repeat
           applies   file contents an action is replacing: the manifest that makes a crash recoverable
           events    the consequence queue (scheduler.py): due_minute, trigger, effect, status
           things    everything else, as (kind, id) → JSON (beliefs, stock, schedules, memories, …)
Files      A handler never writes a campaign file. It returns `writes` {relative path: new text};
           `apply_action` stores them in `applies` in the same transaction that records the result,
           then replaces each file atomically. Opening the store finishes any replace a crash left
           half done, so a reader always sees a complete revision.
Revision   meta.revision goes up by one each time an action's effects are fully applied.
Rolls      `rng(db, key)` is seeded from the campaign's seed and `key`. Give every roll and every
           scheduled event its own key: results then do not depend on how time was sliced.
Hash       `state_hash` covers logical content only (rows and campaign files, no wall-clock stamps),
           so a replay from a snapshot can be compared with the original.
Crash      `crash_point(name)` stops the process when DNE_CRASH_AT names it. Points in use:
           after_input_stored, after_roll, mid_file_replace, after_commit_before_send,
           after_send_before_ack.
Handlers   Engine actions are functions `fn(ctx, intent) -> dict` registered in turn.HANDLERS. They
           call pure rules functions (never a cmd_* that prints or pushes to the display) and return
           {status, elapsed_minutes, writes, visible_events, requests, data}.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

SCHEMA_VERSION = 1
DB_NAME = "world.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta    (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS inputs  (input_id TEXT PRIMARY KEY, turn_id TEXT, source TEXT, text TEXT, wall REAL);
CREATE TABLE IF NOT EXISTS turns   (turn_id TEXT PRIMARY KEY, seq INTEGER, status TEXT, revision_start INTEGER,
                                    world_minute INTEGER, narration TEXT, wall REAL);
CREATE TABLE IF NOT EXISTS actions (action_id TEXT PRIMARY KEY, turn_id TEXT, seq INTEGER, intent TEXT,
                                    status TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS rolls   (action_id TEXT, key TEXT, result TEXT, PRIMARY KEY (action_id, key));
CREATE TABLE IF NOT EXISTS requests(request_id TEXT PRIMARY KEY, turn_id TEXT, action_id TEXT, kind TEXT,
                                    expected TEXT, question TEXT, status TEXT, answer TEXT, epoch INTEGER);
CREATE TABLE IF NOT EXISTS outbox  (message_id TEXT PRIMARY KEY, turn_id TEXT, audience TEXT, kind TEXT, body TEXT,
                                    status TEXT, attempts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS applies (action_id TEXT, path TEXT, content TEXT, digest TEXT, done INTEGER DEFAULT 0,
                                    PRIMARY KEY (action_id, path));
CREATE TABLE IF NOT EXISTS events  (event_id TEXT PRIMARY KEY, due_minute INTEGER, priority INTEGER DEFAULT 0,
                                    trigger TEXT, preconditions TEXT, cause_id TEXT, effect TEXT, audience TEXT,
                                    status TEXT, applied_minute INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS things  (kind TEXT, id TEXT, data TEXT, PRIMARY KEY (kind, id));
"""

#: Columns that hold wall-clock time or delivery bookkeeping: never part of the logical state.
_NOT_STATE = {"wall", "attempts"}
#: Campaign files whose content is part of the state a replay must reproduce.
STATE_FILES = ("calendar.json", "tracker.json", "world-map.json", "factions.json", "graph.json", "state.md")


def enabled(campaign: str) -> bool:
    """True when this campaign opted in (`world_engine: on` in Session Flags)."""
    return paths.session_flag(campaign, "world_engine", "off") == "on"


def db_path(campaign: str) -> Path:
    return paths.find_campaign(campaign) / DB_NAME


def crash_point(name: str) -> None:
    """Recovery tests stop the process here: DNE_CRASH_AT=<name>."""
    if os.environ.get("DNE_CRASH_AT") == name:
        os._exit(77)


def _open(campaign: str) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path(campaign)), timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    return db


def _ensure(db: sqlite3.Connection, campaign: str) -> None:
    if db.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone():
        return                                  # a current store is never written to just by being read
    db.executescript(SCHEMA)
    seed = hashlib.sha256(f"{campaign}:{time.time_ns()}".encode()).hexdigest()[:16]
    db.executemany("INSERT OR IGNORE INTO meta VALUES (?, ?)",
                   [("schema_version", str(SCHEMA_VERSION)), ("revision", "0"), ("seed", seed), ("turn_seq", "0")])


@contextlib.contextmanager
def writer(campaign: str):
    """The single writer: one transaction, committed on success, rolled back on error, always closed."""
    db = _open(campaign)
    try:
        _ensure(db, campaign)                     # creating the schema commits on its own: do it first
        db.execute("BEGIN IMMEDIATE")
        _recover(db, campaign)
        yield db
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


@contextlib.contextmanager
def reader(campaign: str):
    """Read the store (None when the campaign has none). A replace a crash left half done is finished
    first, so what is read is always a whole revision."""
    if not db_path(campaign).exists():
        yield None
        return
    db = _open(campaign)
    try:
        has = db.execute("SELECT name FROM sqlite_master WHERE name='applies'").fetchone()
        pending = bool(has and db.execute("SELECT 1 FROM applies WHERE done=0 LIMIT 1").fetchone())
    finally:
        db.close()
    if pending:
        with writer(campaign):
            pass
    db = _open(campaign)
    try:
        yield db
    finally:
        db.close()


def meta(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(db, key: str, value) -> None:
    db.execute("INSERT INTO meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def revision(db) -> int:
    return int(meta(db, "revision", "0"))


def next_id(db, counter: str, prefix: str) -> str:
    n = int(meta(db, counter, "0")) + 1
    set_meta(db, counter, n)
    return f"{prefix}-{n}"


def rng(db, key: str) -> random.Random:
    """A generator for one roll or one event. Same campaign + same key = same result, however time was sliced."""
    return random.Random(hashlib.sha256(f"{meta(db, 'seed')}:{key}".encode()).hexdigest())


def roll_once(db, action_id: str, key: str, make) -> dict:
    """The stored result for (action, key); `make()` runs only the first time."""
    row = db.execute("SELECT result FROM rolls WHERE action_id=? AND key=?", (action_id, key)).fetchone()
    if row:
        return json.loads(row["result"])
    result = make()
    db.execute("INSERT INTO rolls VALUES (?, ?, ?)", (action_id, key, json.dumps(result, ensure_ascii=False)))
    return result


# ── things: every other kind of record ────────────────────────────────────────

def put(db, kind: str, id: str, data: dict) -> None:
    db.execute("INSERT INTO things VALUES (?, ?, ?) ON CONFLICT(kind, id) DO UPDATE SET data=excluded.data",
               (kind, id, json.dumps(data, ensure_ascii=False, sort_keys=True)))


def get(db, kind: str, id: str) -> "dict | None":
    row = db.execute("SELECT data FROM things WHERE kind=? AND id=?", (kind, id)).fetchone()
    return json.loads(row["data"]) if row else None


def all_of(db, kind: str) -> dict:
    return {r["id"]: json.loads(r["data"]) for r in
            db.execute("SELECT id, data FROM things WHERE kind=? ORDER BY id", (kind,))}


def delete(db, kind: str, id: str) -> None:
    db.execute("DELETE FROM things WHERE kind=? AND id=?", (kind, id))


# ── files: staged in the store, replaced atomically, finished after a crash ───

def stage_writes(db, action_id: str, writes: dict) -> None:
    for rel, text in (writes or {}).items():
        db.execute("INSERT OR REPLACE INTO applies VALUES (?, ?, ?, ?, 0)",
                   (action_id, rel, text, hashlib.sha256(text.encode("utf-8")).hexdigest()))


def _replace(campaign: str, rel: str, text: str) -> None:
    target = paths.find_campaign(campaign) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".world-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def _recover(db, campaign: str) -> None:
    """Finish file replaces that were staged but not all done (the process died mid-way)."""
    rows = db.execute("SELECT action_id, path, content FROM applies WHERE done=0 ORDER BY action_id, path").fetchall()
    for row in rows:
        _replace(campaign, row["path"], row["content"])
        db.execute("UPDATE applies SET done=1 WHERE action_id=? AND path=?", (row["action_id"], row["path"]))
    if rows:
        set_meta(db, "revision", revision(db) + len({r["action_id"] for r in rows}))
        db.execute("DELETE FROM applies WHERE done=1")


def apply_staged(campaign: str) -> None:
    """Replace every staged file, then announce the new revision. Call after the staging transaction committed."""
    if not db_path(campaign).exists():
        return
    db = _open(campaign)                          # raw read: recovery must not do this work for us
    try:
        rows = db.execute("SELECT action_id, path, content FROM applies WHERE done=0 ORDER BY action_id, path").fetchall()
    finally:
        db.close()
    for i, row in enumerate(rows):
        _replace(campaign, row["path"], row["content"])
        if i == 0:
            crash_point("mid_file_replace")       # one file is new, the rest and the revision are not
    if rows:
        with writer(campaign):                    # opening the writer marks them done and counts the revision
            pass


# ── time and state ────────────────────────────────────────────────────────────

def now_minute(campaign: str) -> "int | None":
    """Absolute in-world minute from calendar.json; None when the campaign has no calendar."""
    from economy import _calendar_minutes
    return _calendar_minutes(campaign)


def db_digest(path: Path) -> str:
    """Hash of a store's logical content: every table's rows, minus wall-clock and delivery columns."""
    h = hashlib.sha256()
    if not path.exists():
        return h.hexdigest()
    db = sqlite3.connect(str(path))
    try:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            cols = [c[1] for c in db.execute(f"PRAGMA table_info({table})") if c[1] not in _NOT_STATE]
            if table == "meta":
                rows = db.execute("SELECT key, value FROM meta WHERE key != 'seed' ORDER BY key").fetchall()
            else:
                rows = db.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {', '.join(cols)}").fetchall()
            h.update(table.encode())
            h.update(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"))
    finally:
        db.close()
    return h.hexdigest()


def state_hash(campaign: str) -> str:
    """Hash of the game state a replay must reproduce: the store plus the campaign files rules read."""
    camp = paths.find_campaign(campaign)
    h = hashlib.sha256(db_digest(db_path(campaign)).encode())
    files = [camp / f for f in STATE_FILES] + sorted((camp / "characters").glob("*.md"))
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes() if f.is_file() else b"<absent>")
    return h.hexdigest()
