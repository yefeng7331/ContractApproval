"""Local-only comments with immutable task targets and durable retry history."""

import re
import uuid
from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field

from backend.errors import ApiError
from backend.mock_pending import MOCK_PENDING_ID


class WritebackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_version: int = Field(ge=1, strict=True)
    mock_approval_id: str = Field(min_length=1, max_length=100)


def render_comment(payload):
    lines = ['模拟回写（仅本地保存，未发送真实审批平台）',
             f'文档版本：{payload["document_version"]}；确认审查版本：{payload["review_version"]}',
             '风险总评：' + payload['risk_summary'], '正式结论：' + payload['conclusion'],
             '法务批注：' + (payload['annotation'] or '无')]
    retained = [risk for risk in payload['risks'] if risk['retained']]
    lines += ['重点事项：' + risk['risk_type'] + '（' + risk['risk_level'] + '）；最终建议：' + risk['final_suggestion']
              + '；逐项批注：' + (risk['comment'] or '无') for risk in retained]
    if not retained:
        lines.append('无保留风险；不代表合同不存在其他法律风险。')
    return '\n\n'.join(re.sub(r'([\\`*_{}\[\]()<>#+.!|~\-])', r'\\\1', part)
                        for line in lines for part in line.splitlines()) + '\n'


class WritebackStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store

    def initialize(self):
        with self.tasks.model_budget._transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS mock_writebacks (
                task_id TEXT NOT NULL, review_version INTEGER NOT NULL, mock_approval_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('writing','success','failed')),
                comment_id TEXT UNIQUE, markdown TEXT, error TEXT, completed_at TEXT,
                lease_token TEXT, lease_until TEXT,
                PRIMARY KEY(task_id,review_version,mock_approval_id), UNIQUE(task_id,review_version),
                FOREIGN KEY(task_id,review_version) REFERENCES review_versions(task_id,review_version),
                CHECK((state='success' AND comment_id IS NOT NULL AND markdown IS NOT NULL)
                    OR (state!='success' AND comment_id IS NULL AND markdown IS NULL)))''')
            db.execute('''CREATE TABLE IF NOT EXISTS writeback_attempts (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL, review_version INTEGER NOT NULL,
                actor_user_id INTEGER REFERENCES users(id), requested_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, state TEXT NOT NULL, error TEXT,
                FOREIGN KEY(task_id,review_version) REFERENCES mock_writebacks(task_id,review_version))''')

    def _confirmed(self, task_id, actor, version):
        task = self.auth.connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if task is None or (actor.role == 'business' and task['owner_user_id'] != actor.id):
            raise ApiError(404, 'TASK_NOT_FOUND', '任务不存在')
        row = self.auth.connection.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?',
                                           (task_id, version)).fetchone()
        if row is None or row['state'] != 'confirmed':
            raise ApiError(409, 'WRITEBACK_NOT_CONFIRMED', '仅允许已确认审查版本')
        return task

    def _current(self, db, task_id, version, state):
        # An old worker may finish after a new draft or attachment replaces the current review.
        db.execute('''UPDATE tasks SET writeback_status=? WHERE id=? AND current_review_version=?
            AND legal_status='confirmed' AND current_document_version=(SELECT document_version
                FROM review_versions WHERE task_id=? AND review_version=?)''',
                   (state, task_id, version, task_id, version))

    def read(self, task_id, actor, version):
        with self.auth.lock:
            task = self._confirmed(task_id, actor, version)
            row = self.auth.connection.execute('SELECT * FROM mock_writebacks WHERE task_id=? AND review_version=?',
                                               (task_id, version)).fetchone()
            result = {'task_id': task_id, 'review_version': version, 'simulated': True,
                      'mock_approval_id': task['mock_approval_id'], 'state': 'not_written',
                      'comment_id': None, 'completed_at': None}
            result['document_version'] = self.auth.connection.execute(
                'SELECT document_version FROM review_versions WHERE task_id=? AND review_version=?',
                (task_id, version)).fetchone()[0]
            if row:
                result.update({key: row[key] for key in ('mock_approval_id', 'state', 'comment_id', 'completed_at')})
            if actor.role != 'admin':
                result['markdown'] = row['markdown'] if row else None
            if actor.role in ('legal', 'admin'):
                result['error'] = row['error'] if row else None
                result['attempts'] = [dict(attempt) for attempt in self.auth.connection.execute(
                    '''SELECT id,actor_user_id,requested_at,started_at,finished_at,state,error
                       FROM writeback_attempts WHERE task_id=? AND review_version=? ORDER BY rowid''',
                    (task_id, version)).fetchall()]
            return result

    def submit(self, task_id, actor, request):
        with self.tasks.model_budget._transaction() as db:
            task = self._confirmed(task_id, actor, request.review_version)
            if actor.role != 'legal':
                raise ApiError(403, 'FORBIDDEN', '仅法务可触发模拟回写')
            if task['mock_approval_id'] is not None and task['mock_approval_id'] != request.mock_approval_id:
                raise ApiError(409, 'WRITEBACK_TARGET_CONFLICT', '任务已绑定其他模拟审批单')
            if request.mock_approval_id != MOCK_PENDING_ID:
                raise ApiError(404, 'MOCK_PENDING_NOT_FOUND', '模拟审批单不存在')
            snapshot = db.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?',
                                  (task_id, request.review_version)).fetchone()
            self.tasks.reviews._load(snapshot)
            db.execute('UPDATE tasks SET mock_approval_id=? WHERE id=? AND mock_approval_id IS NULL',
                       (request.mock_approval_id, task_id))
            key = (task_id, request.review_version)
            row = db.execute('SELECT state FROM mock_writebacks WHERE task_id=? AND review_version=?', key).fetchone()
            if row is None or row['state'] == 'failed':
                db.execute('''INSERT INTO mock_writebacks(task_id,review_version,mock_approval_id,state)
                    VALUES (?,?,?,'writing') ON CONFLICT(task_id,review_version) DO UPDATE
                    SET state='writing',error=NULL,lease_token=NULL,lease_until=NULL''', (*key, request.mock_approval_id))
                db.execute('''INSERT INTO writeback_attempts(id,task_id,review_version,actor_user_id,requested_at,state)
                    VALUES (?,?,?,?,?,'writing')''', (uuid.uuid4().hex, *key, actor.id, self.auth._clock().isoformat()))
                self._current(db, *key, 'writing')
                db.execute('''INSERT INTO audit_events
                    (task_id,actor_user_id,action,document_version,created_at)
                    SELECT ?,?,'mock_writeback_requested',document_version,?
                    FROM review_versions WHERE task_id=? AND review_version=?''',
                    (task_id, actor.id, self.auth._clock().isoformat(), *key))
            return self.read(task_id, actor, request.review_version)

    def run_next(self):
        with self.tasks.model_budget._transaction() as db:
            now = self.auth._clock()
            row = db.execute('''SELECT * FROM mock_writebacks WHERE state='writing'
                AND (lease_until IS NULL OR lease_until<=?) ORDER BY rowid LIMIT 1''', (now.isoformat(),)).fetchone()
            if row is None:
                return None
            key = (row['task_id'], row['review_version'])
            attempt = db.execute('''SELECT * FROM writeback_attempts WHERE task_id=? AND review_version=?
                AND state='writing' ORDER BY rowid DESC LIMIT 1''', key).fetchone()
            if row['lease_token']:
                db.execute("UPDATE writeback_attempts SET state='failed',error='WRITEBACK_INTERRUPTED',finished_at=? WHERE id=?",
                           (now.isoformat(), attempt['id']))
                token = uuid.uuid4().hex
                db.execute('''INSERT INTO writeback_attempts(id,task_id,review_version,actor_user_id,requested_at,state)
                    VALUES (?,?,?,?,?,'writing')''', (token, *key, attempt['actor_user_id'], now.isoformat()))
            else:
                token = attempt['id']
            db.execute('UPDATE writeback_attempts SET started_at=? WHERE id=?', (now.isoformat(), token))
            db.execute('UPDATE mock_writebacks SET lease_token=?,lease_until=? WHERE task_id=? AND review_version=?',
                       (token, (now+timedelta(minutes=2)).isoformat(), *key))
            snapshot = db.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?', key).fetchone()
        try:
            markdown = render_comment(self.tasks.reviews._load(snapshot))
            if not markdown:
                raise ValueError('empty comment')
            state, error = 'success', None
        except Exception:
            markdown, state, error = None, 'failed', 'MOCK_WRITEBACK_FAILED'
        with self.tasks.model_budget._transaction() as db:
            # ponytail: local SQLite comment and outcome share one transaction; no external sink or outbox.
            changed = db.execute('''UPDATE mock_writebacks SET state=?,markdown=?,comment_id=?,error=?,completed_at=?,
                lease_token=NULL,lease_until=NULL WHERE task_id=? AND review_version=? AND state='writing' AND lease_token=?''',
                (state, markdown, 'mock-comment-'+uuid.uuid4().hex if markdown else None, error,
                 self.auth._clock().isoformat() if markdown else None, *key, token)).rowcount
            if not changed:
                return 'stale_lease'
            db.execute('UPDATE writeback_attempts SET state=?,error=?,finished_at=? WHERE id=?',
                       (state, error, self.auth._clock().isoformat(), token))
            self._current(db, *key, state)
            db.execute('''INSERT INTO audit_events
                (task_id,actor_user_id,action,document_version,created_at)
                SELECT ?,?, ?,document_version,?
                FROM review_versions WHERE task_id=? AND review_version=?''',
                (key[0], attempt['actor_user_id'],
                 'mock_writeback_succeeded' if state == 'success' else 'mock_writeback_failed',
                 self.auth._clock().isoformat(), *key))
        return state
