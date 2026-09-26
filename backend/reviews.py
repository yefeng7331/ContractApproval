"""Versioned legal decisions and immutable, role-filtered confirmation snapshots."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.errors import ApiError


class RiskDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    rule_id: str = Field(min_length=1, max_length=100)
    retained: bool = Field(strict=True)
    risk_level: Literal['high', 'medium', 'low']
    suggestion_source: Literal['rule', 'model', 'manual']
    final_suggestion: str = Field(default='', max_length=10000)
    comment: str = Field(default='', max_length=10000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    document_version: int = Field(ge=1, strict=True)
    base_review_version: int | None = Field(ge=1, strict=True)
    risks: list[RiskDecision] = Field(max_length=100)
    annotation: str = Field(default='', max_length=20000)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    document_version: int = Field(ge=1, strict=True)
    review_version: int = Field(ge=1, strict=True)
    conclusion: str = Field(min_length=1, max_length=10000)


def _encode(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _digest(data):
    return hashlib.sha256(_encode(data).encode()).hexdigest()


class ReviewStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store

    def initialize(self):
        with self.auth.lock, self.auth.connection:
            self.auth.connection.execute('''CREATE TABLE IF NOT EXISTS review_versions (
                task_id TEXT NOT NULL, review_version INTEGER NOT NULL,
                document_version INTEGER NOT NULL, state TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
                confirmed_by INTEGER REFERENCES users(id), confirmed_at TEXT,
                PRIMARY KEY(task_id,review_version),
                FOREIGN KEY(task_id,document_version) REFERENCES document_versions(task_id,version),
                CHECK(state IN ('in_review','confirmed')))''')

    def _task(self, task_id, actor):
        row = self.auth.connection.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None or (actor.role == 'business' and row['owner_user_id'] != actor.id):
            raise ApiError(404, 'TASK_NOT_FOUND', '任务不存在')
        if actor.role not in ('legal', 'business'):
            raise ApiError(403, 'FORBIDDEN', '无权读取或复核合同内容')
        return row

    def _write_task(self, task_id, actor, document_version, base):
        task = self._task(task_id, actor)
        if actor.role != 'legal':
            raise ApiError(403, 'FORBIDDEN', '仅法务可编辑或确认')
        if task['current_document_version'] != document_version or task['current_review_version'] != base:
            raise ApiError(409, 'REVIEW_VERSION_CONFLICT', '版本已变化，请重新读取后提交')
        if task['machine_status'] != 'completed':
            raise ApiError(409, 'REVIEW_NOT_READY', '机器草稿完成后才能复核')
        return task

    def _source(self, task_id, actor, version):
        # Freeze all report inputs now; later edits and rule upgrades cannot rewrite history.
        document = self.tasks.get_parsed_document(task_id, actor, version)
        document.pop('preview_available', None)  # Artifact readiness is not contract evidence.
        rules = self.tasks.get_rule_snapshot(task_id, actor, version)
        model = self.tasks.model_jobs.read(task_id, actor, version)
        rules.pop('rule_version_current', None)
        model.pop('rule_version_current', None)
        row = self.auth.connection.execute('''SELECT t.department,t.applicant,d.sha256,d.file_path
            FROM tasks t JOIN document_versions d ON d.task_id=t.id WHERE t.id=? AND d.version=?''',
            (task_id, version)).fetchone()
        self.tasks.previews._read_file(row['file_path'], task_id, row['sha256'])
        return {'document': document, 'rules': rules, 'model': model,
                'submission': {key: row[key] for key in ('department', 'applicant', 'sha256')}}

    def _load(self, row):
        try:
            payload = json.loads(row['payload_json'])
            if not isinstance(payload, dict) or _digest(payload) != row['payload_sha256']:
                raise ValueError
            return payload
        except (ValueError, TypeError):
            raise ApiError(409, 'REVIEW_EVIDENCE_INVALID', '审查快照损坏') from None

    def save(self, task_id, actor, request: ReviewRequest):
        with self.tasks.model_budget._transaction() as connection:
            self._write_task(task_id, actor, request.document_version, request.base_review_version)
            source = self._source(task_id, actor, request.document_version)
            rules = source['rules']['risks']
            decisions = {item.rule_id: item for item in request.risks}
            if len(decisions) != len(request.risks) or set(decisions) != {r['rule_id'] for r in rules}:
                raise ApiError(422, 'REVIEW_RISKS_INVALID', '须逐项提交所有规则风险，不得重复或新增未知风险')
            model = {item['rule_id']: item['suggestion'] for item in source['model']['suggestions']}
            risks = []
            for rule in rules:
                decision = decisions[rule['rule_id']]
                suggestion = decision.final_suggestion
                if decision.suggestion_source != 'manual':
                    suggestion = rule['suggestion'] if decision.suggestion_source == 'rule' else model.get(rule['rule_id'], '')
                    if decision.final_suggestion and decision.final_suggestion != suggestion:
                        raise ApiError(422, 'REVIEW_ADOPTION_INVALID', '编辑建议请使用 manual，采纳必须保持原建议')
                if decision.retained and not suggestion:
                    raise ApiError(422, 'REVIEW_SUGGESTION_REQUIRED', '保留风险须提供最终建议；模型缺失时请人工补充或采纳规则建议')
                risks.append({**rule, **decision.model_dump(), 'final_suggestion': suggestion})
            version = connection.execute('SELECT COALESCE(MAX(review_version),0)+1 FROM review_versions WHERE task_id=?',
                (task_id,)).fetchone()[0]
            for risk in risks:
                risk['review_version'] = version
            levels = [r['risk_level'] for r in risks if r['retained']]
            level = next((level for level in ('high', 'medium', 'low') if level in levels), None)
            payload = {'task_id': task_id, 'document_version': request.document_version,
                'review_version': version, 'base_review_version': request.base_review_version,
                'source': source, 'risks': risks, 'annotation': request.annotation,
                'risk_level': level, 'risk_summary': level or ('未保留风险' if rules else '未发现已启用规则风险'),
                'conclusion': None, 'created_by': actor.username, 'created_at': self.auth._clock().isoformat(),
                'confirmed_by': None, 'confirmed_at': None}
            connection.execute('''INSERT INTO review_versions
                (task_id,review_version,document_version,state,payload_json,payload_sha256,created_by,created_at)
                VALUES (?,?,?,'in_review',?,?,?,?)''',
                (task_id, version, request.document_version, _encode(payload), _digest(payload), actor.id, payload['created_at']))
            connection.execute("UPDATE tasks SET current_review_version=?,legal_status='in_review',writeback_status='not_written' WHERE id=?",
                (version, task_id))
            connection.execute('''INSERT INTO audit_events
                (task_id,actor_user_id,action,document_version,created_at)
                VALUES (?,?,'review_saved',?,?)''',
                (task_id, actor.id, request.document_version, payload['created_at']))
            return self._response(payload, 'in_review', actor)

    def confirm(self, task_id, actor, request: ConfirmRequest):
        with self.tasks.model_budget._transaction() as connection:
            self._write_task(task_id, actor, request.document_version, request.review_version)
            row = connection.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?',
                (task_id, request.review_version)).fetchone()
            if row is None:
                raise ApiError(404, 'REVIEW_VERSION_NOT_FOUND', '审查版本不存在')
            payload = self._load(row)
            if row['state'] == 'confirmed':
                if payload['conclusion'] != request.conclusion:
                    raise ApiError(409, 'REVIEW_ALREADY_CONFIRMED', '已确认内容不可改写，请先创建新草稿')
                return self._response(payload, 'confirmed', actor)
            if payload['source'] != self._source(task_id, actor, request.document_version):
                raise ApiError(409, 'REVIEW_EVIDENCE_CHANGED', '同版来源已变化，不能确认旧草稿')
            payload.update(conclusion=request.conclusion, confirmed_by=actor.username,
                           confirmed_at=self.auth._clock().isoformat())
            connection.execute('''UPDATE review_versions SET state='confirmed',payload_json=?,payload_sha256=?,
                confirmed_by=?,confirmed_at=? WHERE task_id=? AND review_version=?''',
                (_encode(payload), _digest(payload), actor.id, payload['confirmed_at'], task_id, request.review_version))
            connection.execute("UPDATE tasks SET legal_status='confirmed' WHERE id=?", (task_id,))
            self.tasks.reports.enqueue(connection, task_id, request.review_version)
            connection.execute('''INSERT INTO audit_events
                (task_id,actor_user_id,action,document_version,created_at)
                VALUES (?,?,'review_confirmed',?,?)''',
                (task_id, actor.id, request.document_version, payload['confirmed_at']))
            return self._response(payload, 'confirmed', actor)

    def read(self, task_id, actor, document_version=None, review_version=None):
        with self.auth.lock:
            task = self._task(task_id, actor)
            query = 'SELECT * FROM review_versions WHERE task_id=?'
            args = [task_id]
            if document_version is not None:
                query += ' AND document_version=?'
                args.append(document_version)
            elif actor.role == 'legal' and review_version is None:
                query += ' AND document_version=?'
                args.append(task['current_document_version'])
            if review_version is not None:
                query += ' AND review_version=?'
                args.append(review_version)
            if actor.role == 'business':
                query += " AND state='confirmed'"
            row = self.auth.connection.execute(query + ' ORDER BY review_version DESC LIMIT 1', args).fetchone()
            if row is None:
                if actor.role == 'business':
                    raise ApiError(403, 'DOCUMENT_NOT_CONFIRMED', '该版本无可见的已确认结果')
                raise ApiError(404, 'REVIEW_VERSION_NOT_FOUND', '审查版本不存在')
            return self._response(self._load(row), row['state'], actor)

    @staticmethod
    def _response(payload, state, actor):
        result = {**payload, 'status': state, 'persisted': True}
        if actor.role == 'business':
            # Only frozen final opinions and their evidence leave the legal workspace.
            result.pop('source')
            result['risks'] = [{k: v for k, v in r.items() if k not in ('suggestion', 'source')}
                               for r in payload['risks'] if r['retained']]
        return result

    def confirmed_document(self, task_id, actor, version=None):
        review = self.read(task_id, actor, version)
        row = self.auth.connection.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?',
            (task_id, review['review_version'])).fetchone()
        document = self._load(row)['source']['document']
        return {**document, 'review_version': review['review_version']}
