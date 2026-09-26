"""Durable, independently retryable artifacts of immutable confirmation snapshots."""

import hashlib
import io
import re
import uuid
import zipfile
from datetime import timedelta
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict, Field

from backend.docx_preview import convert_docx
from backend.errors import ApiError


class ReportRetryRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_version: int = Field(ge=1, strict=True)


def report_lines(payload):
    """One ordered text representation for both formats; never consult live tasks."""
    source = payload['source']
    fields = {f['name']: f['value'] for f in source['document']['fields']}
    lines = ['合同审查报告', '模拟回写（标识，不代表已回写）']
    for key, label in [('title', '合同标题'), ('contract_number', '合同编号'),
                       ('buyer', '采购方'), ('supplier', '相对方'), ('amount', '金额'),
                       ('currency', '币种'), ('performance_term', '履行期限')]:
        lines.append(f'{label}：{fields.get(key) or "未识别"}')
    for key, label in [('department', '送审部门'), ('applicant', '申请人')]:
        lines.append(f'{label}：{source["submission"][key]}')
    for key, label in [('task_id', '任务编号'), ('document_version', '文档版本'),
                       ('review_version', '审查版本'), ('risk_summary', '综合等级'),
                       ('conclusion', '正式结论'), ('annotation', '法务批注'),
                       ('confirmed_by', '确认人'), ('confirmed_at', '确认时间')]:
        lines.append(f'{label}：{payload[key] or "无"}')
    lines.append('原件 SHA256：' + source['submission']['sha256'])
    retained = [r for r in payload['risks'] if r['retained']]
    if not retained:
        lines.append('无保留风险；不代表合同不存在其他法律风险。')
    for number, risk in enumerate(retained, 1):
        lines.extend([f'风险 {number}：{risk["risk_type"]}（{risk["risk_level"]}）',
                      f'规则依据：{risk["rule_id"]} / {risk["rule_version"]}',
                      '法律依据：待法务核定', '原因：' + risk['trigger_reason'],
                      '最终建议：' + risk['final_suggestion'], '逐项批注：' + (risk['comment'] or '无')])
        if not risk['anchors']:
            lines.append('原文定位：无对应条款；不得推定页码。')
        for anchor in risk['anchors']:
            lines.append(f'原文：{anchor["quote"]}')
            lines.append(f'定位：文档 v{payload["document_version"]}，段落索引（从 0 起）{anchor["paragraph_index"]}，'
                         f'字符 [{anchor["start"]}, {anchor["end"]})，页码 {anchor.get("page") or "未核定"}')
    # XML 1.0 cannot represent control characters. Normalize identically in both formats.
    return [re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', '\ufffd', part)
            for line in lines for part in str(line).splitlines()]


def render_report(payload, format):
    lines = report_lines(payload)
    if format == 'markdown':
        # Escape markup, including HTML and automatic links from user-entered opinions.
        return ('\n\n'.join(re.sub(r'([\\`*_{}\[\]()<>#+.!|~\-])', r'\\\1', line)
                            for line in lines) + '\n').encode('utf-8')
    paragraphs = ''.join('<w:p><w:r><w:rPr><w:rFonts w:ascii="Arial" w:eastAsia="Microsoft YaHei"/>'
                         '<w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">' + escape(line) +
                         '</w:t></w:r></w:p>' for line in lines)
    document = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body>' + paragraphs + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
                '</w:sectPr></w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml', document)
    return convert_docx(buffer.getvalue(), payload['document_version'])[0]


class ReportStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store

    def initialize(self):
        with self.tasks.model_budget._transaction() as db:
            # ponytail: SQLite blobs keep publication atomic for local demo scale.
            # Move artifacts to object storage only when database growth requires it.
            db.execute('''CREATE TABLE IF NOT EXISTS reports (
                task_id TEXT NOT NULL, review_version INTEGER NOT NULL, format TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, content BLOB, sha256 TEXT, generated_at TEXT, lease_token TEXT, lease_until TEXT,
                PRIMARY KEY(task_id,review_version,format),
                FOREIGN KEY(task_id,review_version) REFERENCES review_versions(task_id,review_version),
                CHECK(format IN ('markdown','pdf')), CHECK(state IN ('pending','ready','failed')))''')
            for row in db.execute("SELECT task_id,review_version FROM review_versions WHERE state='confirmed'").fetchall():
                self.enqueue(db, row['task_id'], row['review_version'])

    def enqueue(self, db, task_id, version):
        for format in ('markdown', 'pdf'):
            db.execute('INSERT OR IGNORE INTO reports(task_id,review_version,format) VALUES (?,?,?)',
                       (task_id, version, format))

    def _confirmed(self, task_id, actor, version):
        self.tasks.reviews._task(task_id, actor)
        row = self.auth.connection.execute('SELECT * FROM review_versions WHERE task_id=? AND review_version=?',
                                           (task_id, version)).fetchone()
        if row is None or row['state'] != 'confirmed':
            raise ApiError(409, 'REPORT_NOT_READY', '该版本无可用的已确认报告')
        return self.tasks.reviews._load(row)

    def status(self, task_id, actor, version):
        with self.auth.lock:
            self._confirmed(task_id, actor, version)
            rows = self.auth.connection.execute('SELECT * FROM reports WHERE task_id=? AND review_version=? ORDER BY format',
                                                (task_id, version)).fetchall()
            keys = ['format', 'state', 'attempts', 'generated_at']
            if actor.role == 'legal':
                keys.append('error')
            return {'task_id': task_id, 'review_version': version,
                    'reports': [{key: row[key] for key in keys} for row in rows]}

    @staticmethod
    def _format(format):
        if format not in ('markdown', 'pdf'):
            raise ApiError(422, 'REPORT_FORMAT_INVALID', '报告格式须为 markdown 或 pdf')

    def download(self, task_id, actor, version, format):
        self._format(format)
        with self.auth.lock:
            self._confirmed(task_id, actor, version)
            row = self.auth.connection.execute('SELECT * FROM reports WHERE task_id=? AND review_version=? AND format=?',
                                               (task_id, version, format)).fetchone()
            if row is None or row['state'] != 'ready':
                raise ApiError(409, 'REPORT_NOT_READY', '报告尚未生成成功')
            if not row['content'] or hashlib.sha256(row['content']).hexdigest() != row['sha256']:
                raise ApiError(409, 'REPORT_EVIDENCE_INVALID', '报告产物校验失败')
            return row['content']

    def retry(self, task_id, actor, version, format):
        self._format(format)
        with self.tasks.model_budget._transaction() as db:
            self._confirmed(task_id, actor, version)
            if actor.role != 'legal':
                raise ApiError(403, 'FORBIDDEN', '仅法务可重试报告')
            changed = db.execute("UPDATE reports SET state='pending',error=NULL WHERE task_id=? AND review_version=? AND format=? AND state='failed'",
                                 (task_id, version, format)).rowcount
            if not changed:
                raise ApiError(409, 'REPORT_RETRY_CONFLICT', '仅失败报告可重试')
            return self.status(task_id, actor, version)

    def run_next(self):
        with self.tasks.model_budget._transaction() as db:
            now = self.auth._clock()
            row = db.execute("SELECT * FROM reports WHERE state='pending' AND (lease_until IS NULL OR lease_until<=?) ORDER BY task_id,review_version,format LIMIT 1",
                             (now.isoformat(),)).fetchone()
            if row is None:
                return None
            key = (row['task_id'], row['review_version'], row['format'])
            token = uuid.uuid4().hex
            db.execute('UPDATE reports SET attempts=attempts+1,lease_token=?,lease_until=? WHERE task_id=? AND review_version=? AND format=?',
                       (token, (now + timedelta(minutes=2)).isoformat(), *key))
            snapshot = db.execute("SELECT * FROM review_versions WHERE task_id=? AND review_version=? AND state='confirmed'", key[:2]).fetchone()
        try:
            payload = self.tasks.reviews._load(snapshot)
            content = render_report(payload, row['format'])
            if not content:
                raise ValueError('empty artifact')
            state, error = 'ready', None
        except Exception:
            # Do not persist raw converter exceptions: they may contain local paths or contract text.
            content, state, error = None, 'failed', 'REPORT_GENERATION_FAILED'
        with self.tasks.model_budget._transaction() as db:
            changed = db.execute('''UPDATE reports SET state=?,content=?,sha256=?,generated_at=?,error=?,lease_token=NULL,lease_until=NULL
                WHERE task_id=? AND review_version=? AND format=? AND state='pending' AND lease_token=?''',
                (state, content, hashlib.sha256(content).hexdigest() if content else None,
                 self.auth._clock().isoformat() if content else None, error, *key, token)).rowcount
        return state if changed else 'stale_lease'
