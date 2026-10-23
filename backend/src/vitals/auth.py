"""Account and session storage for the status dashboard.

Standard library only. Passwords are kept as salted scrypt hashes; session
tokens are stored as SHA-256 digests, so a copy of the database cannot be
replayed as a valid login and no plain credential is ever written to disk.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_LENGTH = 2 ** 14, 8, 1, 32
MIN_PASSWORD_LENGTH = 8
SESSION_COOKIE = "vitals_session"
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}")
SESSION_CHECK_SECONDS = 15

_dummy_lock = threading.Lock()
_dummy_hash = None


class AuthError(ValueError):
    """Invalid account input; safe to show to an operator."""


def validate_username(username):
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise AuthError("用户名只能包含字母、数字、下划线、点、@ 和连字符，最长 64 位")
    return username


def hash_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"密码至少需要 {MIN_PASSWORD_LENGTH} 个字符")
    if len(password) > 200:
        raise AuthError("密码不能超过 200 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                            p=SCRYPT_P, dklen=SCRYPT_LENGTH)
    return "$".join(("scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), salt.hex(), digest.hex()))


def verify_password(password, stored):
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        expected = bytes.fromhex(digest)
        if scheme != "scrypt" or not expected:
            return False
        computed = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                  n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed, expected)


def spend_verification(password):
    """Burn the same work as a real check when an account does not exist."""
    global _dummy_hash
    with _dummy_lock:
        if _dummy_hash is None:
            _dummy_hash = hash_password(secrets.token_urlsafe(24))
    verify_password(password, _dummy_hash)


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    """`users` and `sessions` tables inside the monitor's SQLite file."""

    def __init__(self, path, session_hours=12.0):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.session_ttl = max(300, int(float(session_hours) * 3600))
        self._lock = threading.Lock()
        self._cache = {}
        self.connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
            with self.connection:
                self.connection.execute("""CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY, password TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
                self.connection.execute("""CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                    created_at REAL NOT NULL, last_seen REAL NOT NULL, expires_at REAL NOT NULL)""")
                self.connection.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions (expires_at)")
        except Exception:
            self.connection.close()
            raise

    def count_users(self):
        with self._lock:
            return self.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def has_user(self, username):
        with self._lock:
            return self.connection.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is not None

    def add_user(self, username, password, replace=False):
        """Create an account, or update the password when replace is set."""
        username = validate_username(username)
        stored = hash_password(password)
        now = time.time()
        with self._lock, self.connection:
            if replace:
                cursor = self.connection.execute(
                    """INSERT INTO users (username, password, created_at, updated_at) VALUES (?, ?, ?, ?)
                       ON CONFLICT(username) DO UPDATE SET password=excluded.password, updated_at=excluded.updated_at""",
                    (username, stored, now, now))
                # A password change revokes every existing session for the account.
                self.connection.execute("DELETE FROM sessions WHERE username = ?", (username,))
                for key in [key for key, value in self._cache.items() if value["username"] == username]:
                    self._cache.pop(key, None)
            else:
                cursor = self.connection.execute(
                    "INSERT OR IGNORE INTO users (username, password, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (username, stored, now, now))
        return cursor.rowcount > 0

    def delete_user(self, username):
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM users WHERE username = ?", (username,))
            self.connection.execute("DELETE FROM sessions WHERE username = ?", (username,))
            removed = cursor.rowcount > 0
            for key in [key for key, value in self._cache.items() if value["username"] == username]:
                self._cache.pop(key, None)
        return removed

    def list_users(self):
        with self._lock:
            return [dict(row) for row in self.connection.execute(
                "SELECT username, created_at, updated_at FROM users ORDER BY username")]

    def authenticate(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or not username:
            spend_verification(password if isinstance(password, str) else "")
            return False
        with self._lock:
            row = self.connection.execute("SELECT password FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            # Same cost as a real check, so response time does not reveal accounts.
            spend_verification(password)
            return False
        return verify_password(password, row[0])

    def create_session(self, username):
        token = secrets.token_urlsafe(32)
        key = token_digest(token)
        now = time.time()
        expires = now + self.session_ttl
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO sessions (token_hash, username, created_at, last_seen, expires_at) VALUES (?, ?, ?, ?, ?)",
                (key, username, now, now, expires))
            self._cache[key] = {"username": username, "expires": expires, "checked": now}
        return token

    def resolve_session(self, token):
        if not isinstance(token, str) or not 16 <= len(token) <= 200:
            return None
        key = token_digest(token)
        now = time.time()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached["expires"] > now and now - cached["checked"] < SESSION_CHECK_SECONDS:
                return cached["username"]
            row = self.connection.execute(
                "SELECT username, expires_at FROM sessions WHERE token_hash = ?", (key,)).fetchone()
            if row is None or row[1] <= now:
                if row is not None:
                    with self.connection:
                        self.connection.execute("DELETE FROM sessions WHERE token_hash = ?", (key,))
                self._cache.pop(key, None)
                return None
            username = row[0]
            # Slide the expiry window, writing at most once a minute per session.
            expires = now + self.session_ttl
            with self.connection:
                self.connection.execute(
                    "UPDATE sessions SET last_seen = ?, expires_at = ? WHERE token_hash = ?", (now, expires, key))
            self._cache[key] = {"username": username, "expires": expires, "checked": now}
            return username

    def delete_session(self, token):
        if not isinstance(token, str) or not token:
            return False
        key = token_digest(token)
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM sessions WHERE token_hash = ?", (key,))
            self._cache.pop(key, None)
        return cursor.rowcount > 0

    def prune_sessions(self, cutoff=None):
        moment = time.time() if cutoff is None else cutoff
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (moment,))
            for key in [key for key, value in self._cache.items() if value["expires"] <= moment]:
                self._cache.pop(key, None)
        return max(0, cursor.rowcount)

    def close(self):
        with self._lock:
            self.connection.close()
