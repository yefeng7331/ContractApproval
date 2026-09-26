"""Durable model drafts; background processing never authorizes paid dispatch."""

import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path

from backend.errors import ApiError
from backend.model_advice import validate_response
from backend.model_transport import prepare_request, _post_json


F1_SHA256 = '5664c685de060fe11deb194bf75d1aadf628594f3b83a48780c315386c742d42'
F1_AUTHORIZATION = 'D-15:F1:one-call'
LEASE_SECONDS = 180


class ModelJobStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store
        self.budget = tasks.model_budget

    def initialize(self):
        with self.auth.lock, self.auth.connection:
            self.auth.connection.executescript('''
                CREATE TABLE IF NOT EXISTS model_jobs (
                    task_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','running','completed','blocked','superseded')),
                    call_id TEXT UNIQUE,
                    authorization_key TEXT UNIQUE,
                    request_sha256 TEXT,
                    evidence_sha256 TEXT,
                    rule_version TEXT,
                    result_json TEXT,
                    code TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    deadline TEXT,
                    finished_at TEXT,
                    PRIMARY KEY(task_id,document_version),
                    FOREIGN KEY(task_id,document_version) REFERENCES document_versions(task_id,version)
                );
            ''')

    def _snapshot(self, task_id, version):
        row = self.auth.connection.execute('''SELECT * FROM parsed_documents
            WHERE task_id=? AND document_version=?''', (task_id, version)).fetchone()
        if row is None or row['structured_extraction_status'] != 'available':
            raise ApiError(409, 'MODEL_EVIDENCE_INVALID', '同版结构化证据尚未就绪')
        try:
            document = dict(task_id=task_id, document_version=version,
                normalized_text=row['normalized_text'], page_count=row['page_count'],
                clauses=json.loads(row['clauses_json']), paragraphs=json.loads(row['paragraphs_json']),
                missing_clause_types=json.loads(row['missing_clause_types_json']))
            snapshot = self.tasks.rule_snapshots.read(document)
        except (ValueError, TypeError, KeyError):
            raise ApiError(409, 'MODEL_EVIDENCE_INVALID', '同版结构化证据损坏') from None
        if not snapshot['rule_version_current']:
            raise ApiError(409, 'RULE_VERSION_CHANGED', '规则版本已变化，需重新送审')
        return snapshot

    def _block(self, connection, task_id, version, code):
        now = self.auth._clock().isoformat()
        connection.execute('''UPDATE model_jobs SET state='blocked', code=?, finished_at=?
            WHERE task_id=? AND document_version=?''', (code, now, task_id, version))
        connection.execute('''UPDATE tasks SET machine_status='blocked', blocked_code=?,
            blocked_reason='模型处理受阻；未自动重试，需核对授权或费用', recovery_action='none'
            WHERE id=? AND current_document_version=? AND machine_status='reviewing' ''',
            (code, task_id, version))

    def refresh(self):
        """Register ready versions and expire uncertain calls without requeuing them."""
        now = self.auth._clock().isoformat()
        with self.budget._transaction() as connection:
            connection.execute('''INSERT OR IGNORE INTO model_jobs
                (task_id,document_version,state,created_at)
                SELECT r.task_id,r.document_version,'pending',? FROM rule_draft_snapshots r
                JOIN tasks t ON t.id=r.task_id AND t.current_document_version=r.document_version
                WHERE t.machine_status='reviewing' ''', (now,))
            connection.execute('''UPDATE model_jobs SET state='superseded', finished_at=?
                WHERE state='pending' AND NOT EXISTS (SELECT 1 FROM tasks t
                WHERE t.id=model_jobs.task_id AND t.current_document_version=model_jobs.document_version)''', (now,))
            expired = connection.execute("SELECT * FROM model_jobs WHERE state='running' AND deadline<=?", (now,)).fetchall()
            for job in expired:
                self.budget.settle(job['call_id'])
                self._block(connection, job['task_id'], job['document_version'], 'MODEL_OUTCOME_UNKNOWN')

    def run_next(self):
        """Only no-cost versions finish automatically; paid jobs await explicit dispatch."""
        self.refresh()
        with self.auth.lock:
            pending = self.auth.connection.execute("SELECT task_id,document_version FROM model_jobs WHERE state='pending' ORDER BY created_at").fetchall()
        # ponytail: scan pending demo jobs; add an indexed authorization queue if scale requires it.
        for job in pending:
            result = self.run_once(job['task_id'], job['document_version'])
            if result['state'] != 'pending':
                return result
        return {'state': 'pending' if pending else 'idle'}

    def run_once(self, task_id, version, *, send=None, authorization_key=None):
        """Internal runner. Production sends enter only through run_authorized_f1."""
        self.refresh()
        with self.budget._transaction() as connection:
            job = connection.execute('SELECT * FROM model_jobs WHERE task_id=? AND document_version=?', (task_id, version)).fetchone()
            if job is None:
                raise ApiError(409, 'MODEL_JOB_NOT_READY', '模型作业尚未就绪')
            if job['state'] != 'pending':
                return {'state': job['state'], 'code': job['code']}
            task = connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if task['current_document_version'] != version or task['machine_status'] != 'reviewing':
                return {'state': 'stale'}
            try:
                snapshot = self._snapshot(task_id, version)
                if snapshot['risks'] and send is None:
                    return {'state': 'pending', 'code': 'MODEL_AUTHORIZATION_REQUIRED'}
                prepared = prepare_request(snapshot)
            except ApiError as error:
                self._block(connection, task_id, version, error.code)
                return {'state': 'blocked', 'code': error.code}
            if prepared is None:
                result = validate_response(snapshot, {})
                result.update(requires_legal_supplement=False, code='MODEL_NOT_REQUIRED')
                self._save(connection, task_id, version, result)
                return {'state': 'completed', 'code': 'MODEL_NOT_REQUIRED'}
            if not isinstance(authorization_key, str) or not authorization_key.strip():
                raise ApiError(409, 'MODEL_AUTHORIZATION_REQUIRED', '尚无本次调用授权')
            if connection.execute('SELECT 1 FROM model_jobs WHERE authorization_key=?', (authorization_key,)).fetchone():
                raise ApiError(409, 'MODEL_AUTHORIZATION_USED', '该次调用授权已使用，不得再次发送')
            call_id = f'model:{task_id}:{version}'
            reserved = self.budget.reserve(call_id, task_id, version, **prepared['quote'])
            if not reserved['created']:
                self._block(connection, task_id, version,
                    'BUDGET_LIMIT' if reserved['state'] == 'rejected' else 'MODEL_OUTCOME_UNKNOWN')
                return {'state': 'blocked', 'code': 'BUDGET_LIMIT' if reserved['state'] == 'rejected' else 'MODEL_OUTCOME_UNKNOWN'}
            now = self.auth._clock()
            connection.execute('''UPDATE model_jobs SET state='running',call_id=?,authorization_key=?,
                request_sha256=?,evidence_sha256=?,rule_version=?,started_at=?,deadline=?
                WHERE task_id=? AND document_version=?''',
                (call_id, authorization_key, prepared['request_sha256'], snapshot['evidence_sha256'],
                 snapshot['rule_version'], now.isoformat(), (now + timedelta(seconds=LEASE_SECONDS)).isoformat(), task_id, version))
        # Reservation + dispatch marker committed together; never hold the database lock over HTTP.
        try:
            result = validate_response(snapshot, send(prepared['body']))
            error_code = None
        except ApiError as error:
            result, error_code = None, error.code
        except Exception:
            result, error_code = None, 'MODEL_TRANSPORT_FAILED'
        with self.budget._transaction() as connection:
            self.budget.settle(call_id, **((result or {}).get('usage') or {}))
            current = connection.execute('SELECT state,deadline FROM model_jobs WHERE task_id=? AND document_version=?', (task_id, version)).fetchone()
            if current['state'] != 'running':
                return {'state': current['state'], 'code': 'MODEL_LATE_RESULT'}
            if current['deadline'] <= self.auth._clock().isoformat():
                error_code = 'MODEL_TIMEOUT'
            if error_code:
                self._block(connection, task_id, version, error_code)
                return {'state': 'blocked', 'code': error_code}
            try:
                fresh = self._snapshot(task_id, version)
                if any(fresh[k] != snapshot[k] for k in ('evidence_sha256', 'rule_version')):
                    raise ApiError(409, 'MODEL_EVIDENCE_CHANGED', '模型请求证据已变化')
            except ApiError as error:
                self._block(connection, task_id, version, error.code)
                return {'state': 'blocked', 'code': error.code}
            state = self._save(connection, task_id, version, result)
            return {'state': state, 'code': result['code']}

    def _save(self, connection, task_id, version, result):
        current = connection.execute('SELECT current_document_version FROM tasks WHERE id=?', (task_id,)).fetchone()[0] == version
        connection.execute('''UPDATE model_jobs SET state=?,result_json=?,code=?,
            evidence_sha256=?,rule_version=?,finished_at=? WHERE task_id=? AND document_version=?''',
            ('completed' if current else 'superseded', json.dumps(result, ensure_ascii=False), result['code'],
             result['evidence_sha256'], result['rule_version'], self.auth._clock().isoformat(), task_id, version))
        if current:
            connection.execute('''UPDATE tasks SET machine_status='completed',blocked_code=NULL,
                blocked_reason=NULL,recovery_action=NULL WHERE id=? AND current_document_version=?
                AND machine_status='reviewing' ''', (task_id, version))
        return 'completed' if current else 'superseded'

    def read(self, task_id, actor, version=None):
        with self.auth.lock:
            snapshot = self.tasks.get_rule_snapshot(task_id, actor, version)
            job = self.auth.connection.execute('SELECT * FROM model_jobs WHERE task_id=? AND document_version=?',
                (task_id, snapshot['document_version'])).fetchone()
            if job is None or job['result_json'] is None:
                raise ApiError(409, 'MODEL_RESULT_NOT_READY', '该版本尚无模型处理结果')
            if any(job[k] != snapshot[k] for k in ('evidence_sha256', 'rule_version')):
                raise ApiError(409, 'MODEL_EVIDENCE_CHANGED', '模型结果与同版证据不一致')
            try:
                result = json.loads(job['result_json'])
                usage = result['usage']
                response = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant',
                    'content': json.dumps({k: result[k] for k in
                        ('document_version', 'evidence_sha256', 'rule_version', 'suggestions')})}}]}
                if usage is not None:
                    response['usage'] = {'prompt_tokens': usage['input_tokens'],
                        'completion_tokens': usage['output_tokens'],
                        'total_tokens': usage['input_tokens'] + usage['output_tokens']}
                if result['code'] == 'MODEL_RESPONSE_INVALID':
                    response['choices'] = []
                checked = validate_response(snapshot, response)
                if not snapshot['risks']:
                    checked.update(requires_legal_supplement=False, code='MODEL_NOT_REQUIRED')
                if result != checked:
                    raise ValueError
            except (ValueError, TypeError, KeyError, RecursionError):
                raise ApiError(409, 'MODEL_RESULT_INVALID', '模型结果已损坏，不能作为审查依据') from None
            return {'task_id': task_id, 'persisted': True, 'review_version': None,
                    'created_at': job['finished_at'],
                    'rule_version_current': snapshot['rule_version_current'], **result}

    def run_authorized_f1(self, task_id, version):
        """Only the one authorized synthetic F1 may reach the real transport."""
        from backend.model_config import load_api_key

        with self.auth.lock:
            document = self.auth.connection.execute('SELECT sha256,file_path FROM document_versions WHERE task_id=? AND version=?', (task_id, version)).fetchone()
            if document is None or document['sha256'] != F1_SHA256:
                raise ApiError(409, 'MODEL_SYNTHETIC_F1_ONLY', '本次授权仅限固定合成 F1')
            path = Path(document['file_path']).resolve()
            if not path.is_relative_to(self.tasks.upload_root.resolve()) or path.stat().st_size > 25 * 1024 * 1024:
                raise ApiError(409, 'MODEL_EVIDENCE_CHANGED', 'F1 原件路径或大小不符合要求')
            if hashlib.sha256(path.read_bytes()).hexdigest() != F1_SHA256:
                raise ApiError(409, 'MODEL_EVIDENCE_CHANGED', 'F1 原件与登记摘要不一致')
        key = load_api_key()
        return self.run_once(task_id, version, send=lambda body: _post_json(body, key),
                             authorization_key=F1_AUTHORIZATION)


def main():
    from backend.auth import AuthStore
    from backend.main import default_database_path, default_upload_root
    from backend.tasks import TaskStore

    parser = argparse.ArgumentParser(description='Run the single authorized synthetic F1 model call; no retries')
    parser.add_argument('task_id')
    parser.add_argument('document_version', type=int)
    args = parser.parse_args()
    auth = AuthStore(default_database_path())
    try:
        auth.initialize()
        tasks = TaskStore(auth, default_upload_root())
        tasks.initialize()
        result = tasks.model_jobs.run_authorized_f1(args.task_id, args.document_version)
        print(json.dumps(result))
        return 0 if result['state'] == 'completed' else 1
    except (ApiError, ValueError, OSError) as error:
        print(json.dumps({'state': 'blocked', 'code': error.code if isinstance(error, ApiError) else 'MODEL_LOCAL_CONFIG_ERROR'}))
        return 1
    finally:
        auth.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
