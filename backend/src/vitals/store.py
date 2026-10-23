"""SQLite archive: compressed samples, hourly rollup and retention pruning."""
import json
import math
import sqlite3
import threading
import time
import zlib
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

PRUNE_BATCH = 5000

TREND_KEYS = ("cpu", "mem", "temp", "ccd", "nvme", "nvme_s1", "nvme_s2", "hdd", "rx", "tx", "dr", "dw")
ROLLUP_BUCKET = 3600
ROLLUP_MIN_SPAN = 7 * 86400


def encode_archive(value):
    """Compress one JSON payload for the archive (zlib BLOB)."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return zlib.compress(raw, 6)


def decode_archive(raw):
    """Read an archived payload. Legacy rows still hold plain-text JSON."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return json.loads(raw)
    return json.loads(zlib.decompress(raw).decode("utf-8"))


class SQLiteStore:
    """Append-only archive with a bounded retention window.

    Raw JSON payloads are stored zlib-compressed (BLOBs); legacy rows keep
    plain-text JSON and stay readable. Short, serialized writes; independent
    WAL readers. A pruning job deletes rows older than retention_days in small
    committed batches so writers never wait on one large transaction.
    """

    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self.path.chmod(0o600)
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise RuntimeError(f"不支持的数据库版本: {version}")
            columns = ", ".join(f"{key} REAL" for key in TREND_KEYS)
            with self.connection:
                self.connection.execute(f"""CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY,
                    sampled_at REAL NOT NULL UNIQUE,
                    snapshot_json TEXT,
                    {columns}
                )""")
                # Cover trend queries without reading every full snapshot JSON.
                self.connection.execute(f"CREATE INDEX IF NOT EXISTS samples_trend ON samples (sampled_at, {', '.join(TREND_KEYS)})")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS collector_samples (
                    id INTEGER PRIMARY KEY,
                    collector TEXT NOT NULL,
                    recorded_at REAL NOT NULL,
                    updated_at TEXT,
                    data_json TEXT,
                    error TEXT
                )""")
                self.connection.execute("""CREATE INDEX IF NOT EXISTS collector_time
                    ON collector_samples (collector, recorded_at)""")
                columns_present = {row[1] for row in self.connection.execute("PRAGMA table_info(collector_samples)")}
                if "metadata_json" not in columns_present:
                    self.connection.execute("ALTER TABLE collector_samples ADD COLUMN metadata_json TEXT")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, occurred_at REAL NOT NULL,
                    incident_key TEXT NOT NULL, phase TEXT NOT NULL, category TEXT NOT NULL,
                    label TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
                    started_at REAL NOT NULL, duration_seconds REAL
                )""")
                self.connection.execute("CREATE INDEX IF NOT EXISTS events_time ON events (occurred_at DESC)")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS incident_states (
                    incident_key TEXT PRIMARY KEY, state_json TEXT NOT NULL
                )""")
                # Hourly rollup keeps month-scale charts fast without touching
                # the raw samples; every trend keeps its own weighted sum/count.
                rollup_columns = ", ".join(f"{key}_sum REAL, {key}_n INTEGER" for key in TREND_KEYS)
                self.connection.execute(f"""CREATE TABLE IF NOT EXISTS samples_hourly (
                    bucket INTEGER PRIMARY KEY,
                    samples INTEGER NOT NULL,
                    {rollup_columns}
                )""")
                self.connection.execute("PRAGMA user_version=4")
        except Exception:
            self.connection.close()
            raise

    def append_sample(self, snapshot, point):
        # A null snapshot denotes a trend imported from the previous service.
        payload = encode_archive(snapshot) if snapshot is not None else None
        values = [point["t"], payload, *(point.get(key) for key in TREND_KEYS)]
        columns = ", ".join(TREND_KEYS)
        placeholders = ", ".join("?" for _ in values)
        with self._lock, self.connection:
            self.connection.execute(
                f"INSERT OR IGNORE INTO samples (sampled_at, snapshot_json, {columns}) VALUES ({placeholders})", values)

    def append_collector(self, name, group, recorded_at=None):
        payload = encode_archive(group["data"])
        metadata = json.dumps({key: group.get(key) for key in ("available", "reason", "attempted_at")}, ensure_ascii=False)
        with self._lock, self.connection:
            self.connection.execute("""INSERT INTO collector_samples
                (collector, recorded_at, updated_at, data_json, error, metadata_json) VALUES (?, ?, ?, ?, ?, ?)""",
                (name, recorded_at if recorded_at is not None else time.time(), group.get("updated_at"), payload, group.get("error"), metadata))

    def prune(self, cutoff):
        """Delete archives older than cutoff, one committed batch at a time."""
        removed = {}
        for table, column in (("samples", "sampled_at"), ("collector_samples", "recorded_at"), ("events", "occurred_at")):
            total = 0
            while True:
                with self._lock, self.connection:
                    cursor = self.connection.execute(
                        f"DELETE FROM {table} WHERE id IN (SELECT id FROM {table} WHERE {column} < ? LIMIT ?)",
                        (cutoff, PRUNE_BATCH))
                total += max(0, cursor.rowcount)
                if cursor.rowcount < PRUNE_BATCH:
                    break
            removed[table] = total
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM samples_hourly WHERE bucket < ?", (cutoff,))
        removed["samples_hourly"] = max(0, cursor.rowcount)
        return removed

    def rollup(self, start, end):
        """Aggregate raw samples into hourly buckets; safe to run repeatedly."""
        sums = ", ".join(f"SUM({key}), COUNT({key})" for key in TREND_KEYS)
        insert_columns = ", ".join(f"{key}_sum, {key}_n" for key in TREND_KEYS)
        updates = ", ".join(f"{key}_sum=excluded.{key}_sum, {key}_n=excluded.{key}_n" for key in TREND_KEYS)
        with self._lock, self.connection:
            cursor = self.connection.execute(f"""
                INSERT INTO samples_hourly (bucket, samples, {insert_columns})
                SELECT CAST(sampled_at / 3600 AS INTEGER) * 3600, COUNT(*), {sums}
                FROM samples WHERE sampled_at >= ? AND sampled_at < ?
                GROUP BY 1
                ON CONFLICT(bucket) DO UPDATE SET samples=excluded.samples, {updates}""",
                (start, end))
        return max(0, cursor.rowcount)

    def rollup_bounds(self):
        with self._lock:
            return self.connection.execute("SELECT MIN(bucket), MAX(bucket) FROM samples_hourly").fetchone()

    def last_collector(self, name):
        """Most recent archived observation of one collector."""
        uri = f"file:{quote(str(self.path))}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            return connection.execute("""SELECT recorded_at, updated_at, data_json, error, metadata_json
                FROM collector_samples WHERE collector = ? ORDER BY recorded_at DESC LIMIT 1""",
                (name,)).fetchone()

    def first_sample_at(self):
        uri = f"file:{quote(str(self.path))}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            row = connection.execute("SELECT sampled_at FROM samples ORDER BY sampled_at LIMIT 1").fetchone()
        return row[0] if row else None

    def history(self, start, end, max_points=1800):
        if end - start > ROLLUP_MIN_SPAN:
            return self._history_rollup(start, end, max_points)
        interval = max(1, math.ceil((end - start) / max_points))
        averages = ", ".join(f"AVG({key}) AS {key}" for key in TREND_KEYS)
        # The write connection remains open, so readers do not rebuild WAL state.
        uri = f"file:{quote(str(self.path))}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(f"""SELECT MIN(sampled_at) AS t, {averages}
                FROM samples WHERE sampled_at >= ? AND sampled_at <= ?
                GROUP BY CAST((sampled_at - ?) / ? AS INTEGER)
                ORDER BY t LIMIT ?""", (start, end, start, interval, max_points + 1)).fetchall()
            first = connection.execute("SELECT sampled_at FROM samples ORDER BY sampled_at LIMIT 1").fetchone()
        return {"interval": interval, "points": [dict(row) for row in rows],
                "start": start, "end": end, "resolution": "raw",
                "first_sample_at": first[0] if first else None}

    def _history_rollup(self, start, end, max_points):
        """Merge hourly sums with raw edges of the range, weighted by sample count."""
        interval = max(ROLLUP_BUCKET, math.ceil((end - start) / max_points / ROLLUP_BUCKET) * ROLLUP_BUCKET)
        sums = ", ".join(f"SUM({key}) AS {key}_s, COUNT({key}) AS {key}_n" for key in TREND_KEYS)
        hourly_select = ", ".join(f"{key}_sum AS {key}_s, {key}_n AS {key}_n" for key in TREND_KEYS)
        uri = f"file:{quote(str(self.path))}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            low, high = connection.execute("SELECT MIN(bucket), MAX(bucket) FROM samples_hourly").fetchone()
            hourly_end = high + ROLLUP_BUCKET if high is not None else None
            if low is None:
                segments = [(start, end, False)]
            else:
                segments = [(start, min(low, end), False),
                            (max(start, low), min(end, hourly_end), True),
                            (max(start, hourly_end), end, False)]
            buckets = {}

            def add(index, stamp, values):
                entry = buckets.setdefault(index, {"t": stamp, "sums": {key: [0.0, 0] for key in TREND_KEYS}})
                entry["t"] = min(entry["t"], stamp)
                for key in TREND_KEYS:
                    total, count = values.get(key, (None, 0))
                    if total is not None and count:
                        entry["sums"][key][0] += total
                        entry["sums"][key][1] += count

            for begin, finish, hourly in segments:
                if finish <= begin:
                    continue
                if hourly:
                    rows = connection.execute(f"""SELECT bucket, {hourly_select} FROM samples_hourly
                        WHERE bucket >= ? AND bucket < ?""", (begin, finish)).fetchall()
                    for row in rows:
                        add((row["bucket"] - start) // interval, row["bucket"],
                            {key: (row[f"{key}_s"], row[f"{key}_n"]) for key in TREND_KEYS})
                else:
                    rows = connection.execute(f"""SELECT MIN(sampled_at) AS t,
                        CAST((sampled_at - ?) / ? AS INTEGER) AS bucket, {sums}
                        FROM samples WHERE sampled_at >= ? AND sampled_at < ?
                        GROUP BY bucket""", (start, interval, begin, finish)).fetchall()
                    for row in rows:
                        add(row["bucket"], row["t"],
                            {key: (row[f"{key}_s"], row[f"{key}_n"]) for key in TREND_KEYS})
            first = connection.execute("SELECT sampled_at FROM samples ORDER BY sampled_at LIMIT 1").fetchone()
        points = []
        for index in sorted(buckets):
            entry = buckets[index]
            point = {"t": max(start, entry["t"])}
            for key in TREND_KEYS:
                total, count = entry["sums"][key]
                point[key] = round(total / count, 3) if count else None
            points.append(point)
        return {"interval": interval, "points": points[: max_points + 1],
                "start": start, "end": end, "resolution": "hourly",
                "first_sample_at": first[0] if first else None}

    def load_incident_states(self):
        with self._lock:
            return {key: json.loads(raw) for key, raw in self.connection.execute("SELECT incident_key, state_json FROM incident_states")}

    def commit_events(self, states, events):
        with self._lock, self.connection:
            for key, state in states.items():
                self.connection.execute("""INSERT INTO incident_states (incident_key, state_json) VALUES (?, ?)
                    ON CONFLICT(incident_key) DO UPDATE SET state_json=excluded.state_json""",
                    (key, json.dumps(state, ensure_ascii=False, allow_nan=False)))
            for event in events:
                self.connection.execute("""INSERT INTO events
                    (occurred_at, incident_key, phase, category, label, severity, message, started_at, duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    tuple(event[key] for key in ("occurred_at", "key", "phase", "category", "label", "severity", "message", "started_at", "duration_seconds")))

    def event_feed(self, limit=30, before=None):
        uri = f"file:{quote(str(self.path))}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM events WHERE id < ? ORDER BY id DESC LIMIT ?",
                                      (before if before is not None else 9223372036854775807, limit)).fetchall()
            states = [json.loads(row[0]) for row in connection.execute("SELECT state_json FROM incident_states")]
        return {"events": [dict(row) for row in rows], "active": [s for s in states if s["active"]],
                "next_before": rows[-1]["id"] if len(rows) == limit else None}

    def close(self):
        with self._lock:
            self.connection.close()
