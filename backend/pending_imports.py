"""Durable attachment intake before a document exists; no external platform calls."""

import hashlib
import sqlite3
import uuid
from contextlib import ExitStack
from datetime import timedelta

from backend.errors import ApiError
from backend.mock_pending import MOCK_PENDING_ITEM


class PendingImportStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store

    def initialize(self):
        with self.auth.lock, self.auth.connection:
            self.auth.connection.executescript('''
                CREATE TABLE IF NOT EXISTS attachment_attempts (
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    attempt INTEGER NOT NULL,
                    token TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    error_code TEXT,
                    started_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    finished_at TEXT,
                    actor_user_id INTEGER NOT NULL REFERENCES users(id),
                    PRIMARY KEY(task_id, attempt)
                );
            ''')
        self.recover_expired()

    def _audit(self, db, task, actor, action, now):
        db.execute('''INSERT INTO audit_events
            (task_id,actor_user_id,action,document_version,created_at) VALUES (?,?,?,1,?)''',
            (task, actor, action, now))

    def _claim(self, db, task, actor, attempt, now):
        token = uuid.uuid4().hex
        db.execute('INSERT INTO attachment_attempts VALUES (?,?,?,\'running\',NULL,?,?,NULL,?)',
            (task, attempt, token, now.isoformat(), (now + timedelta(minutes=2)).isoformat(), actor))
        db.execute('''UPDATE tasks SET machine_status='pending',blocked_code=NULL,
            blocked_reason=NULL,recovery_action=NULL,attempt_count=? WHERE id=?''', (attempt, task))
        self._audit(db, task, actor, 'attachment_fetch_started', now.isoformat())
        return token

    def create(self, actor, fetch):
        if actor.role != 'business':
            raise ApiError(403, 'FORBIDDEN', '无权导入待办')
        task = uuid.uuid4().hex
        now = self.auth._clock()
        # Register ownership and attempt BEFORE fetching. No placeholder document or file.
        with self.tasks.model_budget._transaction() as db:
            db.execute('''INSERT INTO tasks (id,owner_user_id,source,department,applicant,business_type,
                created_at,current_document_version,machine_status,legal_status,writeback_status,mock_approval_id)
                VALUES (?,?,'mock_pending',?,?,?,?,1,'pending','pending','not_written',?)''',
                (task, actor.id, MOCK_PENDING_ITEM['department'], MOCK_PENDING_ITEM['applicant'], MOCK_PENDING_ITEM['business_type'],
                 now.isoformat(), MOCK_PENDING_ITEM['id']))
            token = self._claim(db, task, actor.id, 1, now)
        return self._fetch(task, token, 1, actor, fetch)

    def recover_expired(self):
        now = self.auth._clock().isoformat()
        with self.tasks.model_budget._transaction() as db:
            rows = db.execute("SELECT * FROM attachment_attempts WHERE state='running' AND expires_at<=?", (now,)).fetchall()
            for row in rows:
                self._block(db, row, 'ATTACHMENT_FETCH_INTERRUPTED', '附件获取中断，请管理员重试', now)

    def _block(self, db, row, code, reason, now):
        db.execute("UPDATE attachment_attempts SET state='failed',error_code=?,finished_at=? WHERE token=?",
                   (code, now, row['token']))
        db.execute('''UPDATE tasks SET machine_status='blocked',blocked_code=?,blocked_reason=?,
            recovery_action='admin_retry' WHERE id=?''', (code, reason, row['task_id']))
        self._audit(db, row['task_id'], row['actor_user_id'], code.lower(), now)

    def retry(self, task, version, actor, fetch):
        if actor.role != 'admin':
            raise ApiError(403, 'FORBIDDEN', '仅管理员可重试附件获取')
        self.recover_expired()
        with self.tasks.model_budget._transaction() as db:
            row = db.execute('SELECT * FROM attachment_attempts WHERE task_id=? ORDER BY attempt DESC LIMIT 1', (task,)).fetchone()
            if row is None or row['state'] == 'completed':
                return None  # Existing OCR/rule retry contracts handle subsequent stages.
            if version != 1 or row['state'] != 'failed':
                raise ApiError(409, 'TASK_STATE_CONFLICT', '附件正在获取或文档版本不匹配')
            attempt = row['attempt'] + 1
            token = self._claim(db, task, actor.id, attempt, self.auth._clock())
        return self._fetch(task, token, attempt, actor, fetch)

    def _fetch(self, task, token, attempt, actor, fetch):
        from backend.tasks import identify_document

        failure = None
        content = filename = format = None
        try:
            content = fetch(attempt)
            filename, format = identify_document(MOCK_PENDING_ITEM['attachment_filename'], content)
        except TimeoutError:
            failure = ('ATTACHMENT_FETCH_TIMEOUT', '附件获取超时，请管理员重试')
        except Exception:
            # Do not expose adapter exception messages, paths, or credentials.
            failure = ('ATTACHMENT_FETCH_FAILED', '附件获取失败，请管理员检查后重试')
        try:
            return self._publish(task, token, actor, content, filename, format, failure)
        except (OSError, sqlite3.Error):
            return self._publish(task, token, actor, None, None, None,
                ('ATTACHMENT_STORE_FAILED', '附件保存失败，请管理员检查后重试'))

    def _publish(self, task, token, actor, content, filename, format, failure):
        from backend.tasks import stored_attachment

        # The file guard encloses COMMIT as well as the SQL writes.
        with ExitStack() as files, self.tasks.model_budget._transaction() as db:
            row = db.execute('SELECT * FROM attachment_attempts WHERE token=?', (token,)).fetchone()
            now = self.auth._clock().isoformat()
            if row['state'] != 'running':
                return self.tasks.get_task(task, actor)
            if row['expires_at'] <= now:
                failure = ('ATTACHMENT_FETCH_INTERRUPTED', '附件获取中断，请管理员重试')
            if failure:
                self._block(db, row, *failure, now)
            else:
                owner = db.execute('SELECT owner_user_id FROM tasks WHERE id=?', (task,)).fetchone()[0]
                # Unique path also tolerates files left by a process crash before DB commit.
                path = self.tasks.upload_root / task / ('v1-' + token + '.docx')
                files.enter_context(stored_attachment(path, content))
                db.execute('''INSERT INTO document_versions
                    (task_id,version,original_filename,format,sha256,file_path,submitted_by,created_at)
                    VALUES (?,1,?,?,?,?,?,?)''',
                    (task, filename, format, hashlib.sha256(content).hexdigest(), str(path), owner, now))
                self.tasks.jobs.enqueue_parse(task, 1, now)
                db.execute("UPDATE attachment_attempts SET state='completed',finished_at=? WHERE token=?", (now, token))
                self._audit(db, task, actor.id, 'mock_pending_imported', now)
        return self.tasks.get_task(task, actor)

    def history(self, task, actor):
        if actor.role != 'admin':
            raise ApiError(403, 'FORBIDDEN', '仅管理员可查看附件获取尝试')
        self.recover_expired()
        self.tasks.get_task(task, actor)
        with self.auth.lock:
            rows = self.auth.connection.execute('''SELECT attempt,state,error_code,started_at,finished_at,
                actor_user_id FROM attachment_attempts WHERE task_id=? ORDER BY attempt''', (task,)).fetchall()
        return {'task_id': task, 'document_version': 1, 'attempts': [dict(row) for row in rows]}
