"""Immutable DOCX preview artifacts, separate from accepted review evidence."""

import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path

from backend.docx_preview import convert_docx
from backend.errors import ApiError
from backend.pdf_parser import MAX_PDF_BYTES


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PreviewStore:
    def __init__(self, tasks):
        self.tasks = tasks
        self.auth = tasks.auth_store

    def initialize(self):
        with self.auth.lock, self.auth.connection:
            self.auth.connection.execute('''CREATE TABLE IF NOT EXISTS docx_previews (
                task_id TEXT NOT NULL, document_version INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('running','ready','failed')),
                source_sha256 TEXT NOT NULL, parsed_sha256 TEXT NOT NULL,
                preview_sha256 TEXT, preview_path TEXT, mapping_json TEXT, mapping_sha256 TEXT,
                code TEXT, created_at TEXT NOT NULL, deadline TEXT NOT NULL,
                PRIMARY KEY(task_id,document_version),
                FOREIGN KEY(task_id,document_version) REFERENCES document_versions(task_id,version))''')

    def _source(self, task_id, version):
        row = self.auth.connection.execute('''SELECT d.file_path,d.sha256,d.format,
            p.normalized_text,p.paragraphs_json,p.fields_json,p.clauses_json FROM document_versions d
            JOIN parsed_documents p ON p.task_id=d.task_id AND p.document_version=d.version
            WHERE d.task_id=? AND d.version=?''', (task_id, version)).fetchone()
        if row is None or row['format'] not in ('docx', 'png', 'jpeg', 'tiff'):
            raise ApiError(409, 'DOCX_PREVIEW_NOT_READY', '该版本尚无可转换的 DOCX 解析结果')
        data = dict(row)
        data['parsed_sha256'] = _digest([data[k] for k in
            ('normalized_text', 'paragraphs_json', 'fields_json', 'clauses_json')])
        return data

    def _read_file(self, path, task_id, digest):
        try:
            source = Path(path).resolve()
            if not source.is_relative_to((self.tasks.upload_root / task_id).resolve()):
                raise ValueError
            if source.stat().st_size > MAX_PDF_BYTES:
                raise ValueError
            content = source.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError
            return content
        except (OSError, ValueError, RuntimeError):
            raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '预览或原件与登记证据不一致') from None

    def run_next(self):
        with self.tasks.model_budget._transaction() as connection:
            connection.execute("UPDATE docx_previews SET state='failed',code='DOCX_PREVIEW_INTERRUPTED' WHERE state='running' AND deadline<=?",
                (self.auth._clock().isoformat(),))
            row = connection.execute('''SELECT d.task_id,d.version FROM document_versions d
                JOIN tasks t ON t.id=d.task_id AND t.current_document_version=d.version
                JOIN parsed_documents p ON p.task_id=d.task_id AND p.document_version=d.version
                LEFT JOIN docx_previews v ON v.task_id=d.task_id AND v.document_version=d.version
                WHERE d.format IN ('docx','png','jpeg','tiff') AND v.task_id IS NULL ORDER BY p.created_at LIMIT 1''').fetchone()
        return self.build(row['task_id'], row['version']) if row else {'state': 'idle'}

    def build(self, task_id, version):
        with self.tasks.model_budget._transaction() as connection:
            old = connection.execute('SELECT state,code FROM docx_previews WHERE task_id=? AND document_version=?', (task_id, version)).fetchone()
            if old:
                return dict(old)
            source = self._source(task_id, version)
            now = self.auth._clock()
            connection.execute('''INSERT INTO docx_previews
                (task_id,document_version,state,source_sha256,parsed_sha256,created_at,deadline)
                VALUES (?,?,'running',?,?,?,?)''', (task_id, version, source['sha256'], source['parsed_sha256'],
                    now.isoformat(), (now + timedelta(seconds=180)).isoformat()))
        try:
            content = self._read_file(source['file_path'], task_id, source['sha256'])
            if source['format'] == 'docx':
                pdf, mapping = convert_docx(content, version)
            else:
                from backend.ocr import image_preview

                pdf, mapping = image_preview(content, version, source)
            if mapping['normalized_text'] != source['normalized_text']:
                raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '预览正文与已有解析证据不一致')
            if any(mapping[k] != expected for k, expected in
                    [('document_version', version), ('source_sha256', source['sha256']),
                     ('preview_sha256', hashlib.sha256(pdf).hexdigest())]):
                raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '转换产物摘要或版本不一致')
            # Append coordinates to a separate map; never rewrite rule/model snapshots.
            def locate(anchor):
                selected = [p for p in mapping['paragraphs'] if p['start'] < anchor['end'] and p['end'] > anchor['start']]
                valid = (bool(selected) and selected[0]['start'] == anchor['start']
                    and selected[-1]['end'] == anchor['end'] and all(p['locatable'] for p in selected))
                rects = [r for p in selected for r in p['rects']] if valid else []
                return {**anchor, 'page': selected[0]['page'] if selected else None,
                    'locatable': valid, 'rects': rects,
                    'reason': None if valid else ('DOCX_PREVIEW_REGION_UNVERIFIED'
                        if source['format'] == 'docx' else 'OCR_FIELD_REGION_UNVERIFIED')}
            mapping['clauses'] = [locate(c) for c in json.loads(source['clauses_json'])]
            mapping['fields'] = [{**f, 'anchor': locate(f['anchor']) if f['anchor'] else None}
                for f in json.loads(source['fields_json'])]
            with self.tasks.model_budget._transaction() as connection:
                current = connection.execute('SELECT state,deadline FROM docx_previews WHERE task_id=? AND document_version=?', (task_id, version)).fetchone()
                if current['state'] != 'running' or current['deadline'] <= self.auth._clock().isoformat():
                    raise ApiError(409, 'DOCX_PREVIEW_INTERRUPTED', '转换已过期，未发布迟到结果')
                fresh = self._source(task_id, version)
                if fresh['parsed_sha256'] != source['parsed_sha256'] or fresh['sha256'] != source['sha256']:
                    raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '转换期间来源证据发生变化')
                self._read_file(fresh['file_path'], task_id, fresh['sha256'])
                path = self.tasks.upload_root / task_id / ('preview-' + uuid.uuid4().hex + '.pdf')
                with path.open('xb') as output:
                    output.write(pdf)
                # A crash may leave an unreferenced file; it is never served or overwritten.
                connection.execute('''UPDATE docx_previews SET state='ready',preview_path=?,
                    preview_sha256=?,mapping_json=?,mapping_sha256=? WHERE task_id=? AND document_version=?''',
                    (str(path.resolve()), mapping['preview_sha256'], json.dumps(mapping, ensure_ascii=False),
                     _digest(mapping), task_id, version))
            return {'state': 'ready', 'code': None}
        except Exception as error:
            code = getattr(error, 'code', 'DOCX_PREVIEW_FAILED')
            with self.tasks.model_budget._transaction() as connection:
                connection.execute("UPDATE docx_previews SET state='failed',code=? WHERE task_id=? AND document_version=? AND state='running'",
                    (code, task_id, version))
            return {'state': 'failed', 'code': code}

    def read(self, task_id, actor, version=None):
        with self.auth.lock:
            document = self.tasks.get_parsed_document(task_id, actor, version)
            version = document['document_version']
            row = self.auth.connection.execute('SELECT * FROM docx_previews WHERE task_id=? AND document_version=?', (task_id, version)).fetchone()
            if row is None or row['state'] != 'ready':
                raise ApiError(409, row['code'] if row and row['code'] else 'DOCX_PREVIEW_NOT_READY', '该版本固定预览尚不可用')
            source = self._source(task_id, version)
            if source['sha256'] != row['source_sha256'] or source['parsed_sha256'] != row['parsed_sha256']:
                raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '预览与当前同版证据不一致')
            self._read_file(source['file_path'], task_id, source['sha256'])
            content = self._read_file(row['preview_path'], task_id, row['preview_sha256'])
            try:
                mapping = json.loads(row['mapping_json'])
                if _digest(mapping) != row['mapping_sha256']:
                    raise ValueError
            except (ValueError, TypeError):
                raise ApiError(409, 'PREVIEW_EVIDENCE_CHANGED', '预览定位证据已损坏') from None
            return content, {'task_id': task_id, 'persisted': True, **mapping}
