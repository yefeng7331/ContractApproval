"""Local demo identities and revocable bearer sessions."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


ROLES = ("business", "legal", "admin")
SESSION_TTL = timedelta(hours=8)
PASSWORD_ITERATIONS = 600_000
USERNAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,63}\Z")
DUMMY_SALT = b"ContractApproval!"


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str


@dataclass(frozen=True)
class Session:
    token: str
    expires_at: datetime
    user: User


class AuthStore:
    """Single-process SQLite store; every operation is serialized per instance."""

    def __init__(
        self,
        database_path: str | Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        path = str(database_path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL CHECK (role IN ('business', 'legal', 'admin')),
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def create_user(self, username: str, role: str, password: str) -> User:
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("用户名须为 3–64 位英文字母、数字、点、下划线或连字符")
        if role not in ROLES:
            raise ValueError("无效角色")
        if len(password) < 12:
            raise ValueError("密码至少 12 个字符")
        salt = secrets.token_bytes(16)
        password_hash = self._hash_password(password, salt)
        with self._lock:
            try:
                with self._connection:
                    cursor = self._connection.execute(
                        """INSERT INTO users
                        (username, role, password_salt, password_hash, created_at)
                        VALUES (?, ?, ?, ?, ?)""",
                        (username, role, salt, password_hash, self._now().isoformat()),
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError("用户名已存在") from exc
        return User(int(cursor.lastrowid), username, role)

    def authenticate(self, username: str, password: str) -> User | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT id, username, role, password_salt, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        salt = bytes(row["password_salt"]) if row else DUMMY_SALT
        candidate = self._hash_password(password, salt)
        expected = bytes(row["password_hash"]) if row else b"\0" * len(candidate)
        if not hmac.compare_digest(candidate, expected) or row is None:
            return None
        return User(int(row["id"]), str(row["username"]), str(row["role"]))

    def create_session(self, username: str, password: str) -> Session | None:
        user = self.authenticate(username, password)
        if user is None:
            return None
        token = secrets.token_urlsafe(32)
        now = self._now()
        expires_at = now + SESSION_TTL
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)""",
                (self._token_hash(token), user.id, now.isoformat(), expires_at.isoformat()),
            )
        return Session(token, expires_at, user)

    def resolve_session(self, token: str) -> User | None:
        if not token:
            return None
        with self._lock:
            row = self._connection.execute(
                """SELECT u.id, u.username, u.role, s.expires_at, s.revoked_at
                FROM sessions AS s JOIN users AS u ON u.id = s.user_id
                WHERE s.token_hash = ?""",
                (self._token_hash(token),),
            ).fetchone()
        if row is None or row["revoked_at"] is not None:
            return None
        if datetime.fromisoformat(str(row["expires_at"])) <= self._now():
            return None
        return User(int(row["id"]), str(row["username"]), str(row["role"]))

    def revoke_session(self, token: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (self._now().isoformat(), self._token_hash(token)),
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("Clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _hash_password(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
