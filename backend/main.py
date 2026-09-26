"""HTTP entry point for the local demo backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.auth import AuthStore, User
from backend.errors import ApiError, api_error_handler, validation_error_handler
from backend.mock_pending import MOCK_PENDING_ID, MOCK_PENDING_ITEM, synthetic_attachment
from backend.tasks import MAX_UPLOAD_BYTES, TaskStore
from backend.reviews import ReviewRequest, ConfirmRequest
from backend.reports import ReportRetryRequest
from backend.writeback import WritebackRequest


bearer_scheme = HTTPBearer(auto_error=False)


def fetch_pending_attachment(attempt: int) -> bytes:
    """Local adapter; its persisted attempt is available to the F6 fault fixture."""
    return synthetic_attachment()


def default_database_path() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "contract_approval.sqlite3"


def default_upload_root() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "uploads"


class LoginRequest(BaseModel):
    username: str
    password: str = Field(repr=False)


class RetryRequest(BaseModel):
    document_version: int = Field(ge=1)


class UserResponse(BaseModel):
    username: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_at: str
    user: UserResponse


def get_auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store


def get_task_store(request: Request) -> TaskStore:
    return request.app.state.task_store


def current_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    return credentials.credentials


def current_user(
    token: Annotated[str, Depends(current_token)],
    store: Annotated[AuthStore, Depends(get_auth_store)],
) -> User:
    user = store.resolve_session(token)
    if user is None:
        raise ApiError(401, "AUTH_INVALID", "登录已失效，请重新登录")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Reusable server-side role check for later business routes."""

    def check(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN", "无权执行此操作")
        return user

    return check


def create_app(
    database_path: str | Path | None = None,
    auth_store: AuthStore | None = None,
    upload_root: str | Path | None = None,
    *,
    auto_process_docx: bool = False,
    auto_process_pdf: bool = False,
    auto_process_ocr: bool = False,
    auto_process_rules: bool = False,
    auto_process_models: bool = False,
    auto_process_previews: bool = False,
    auto_process_reports: bool = False,
    auto_process_writebacks: bool = False,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = auth_store or AuthStore(database_path or default_database_path())
        store.initialize()
        task_store = TaskStore(store, upload_root or default_upload_root())
        task_store.initialize()
        app.state.auth_store = store
        app.state.task_store = task_store
        worker = None
        if auto_process_docx or auto_process_pdf or auto_process_ocr or auto_process_rules or auto_process_models or auto_process_previews or auto_process_reports or auto_process_writebacks:
            from backend.docx_worker import DocxWorker

            task_store.jobs.recover_expired()
            worker = DocxWorker(task_store.jobs, process_pdf=auto_process_pdf, process_ocr=auto_process_ocr,
                                rule_snapshots=task_store.rule_snapshots if auto_process_rules else None,
                                model_jobs=task_store.model_jobs if auto_process_models else None,
                                previews=task_store.previews if auto_process_previews else None,
                                reports=task_store.reports if auto_process_reports else None,
                                writebacks=task_store.writebacks if auto_process_writebacks else None,
                                pending_imports=task_store.pending_imports)
            worker.start()
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()
            if auth_store is None:
                store.close()

    app = FastAPI(title="ContractApproval Demo API", lifespan=lifespan)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.post("/api/v1/sessions", response_model=LoginResponse)
    def login(payload: LoginRequest, store: Annotated[AuthStore, Depends(get_auth_store)]):
        session = store.create_session(payload.username, payload.password)
        if session is None:
            raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码错误")
        return LoginResponse(
            access_token=session.token,
            token_type="bearer",
            expires_at=session.expires_at.isoformat(),
            user=UserResponse(username=session.user.username, role=session.user.role),
        )

    @app.get("/api/v1/sessions/current", response_model=UserResponse)
    def session_info(user: Annotated[User, Depends(current_user)]):
        return UserResponse(username=user.username, role=user.role)

    @app.delete("/api/v1/sessions/current", status_code=204)
    def logout(
        token: Annotated[str, Depends(current_token)],
        user: Annotated[User, Depends(current_user)],
        store: Annotated[AuthStore, Depends(get_auth_store)],
    ) -> None:
        _ = user
        store.revoke_session(token)

    @app.post("/api/v1/tasks", status_code=201)
    async def create_task(
        actor: Annotated[User, Depends(require_roles("business"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        file: Annotated[UploadFile, File()],
        department: Annotated[str, Form()],
        applicant: Annotated[str, Form()],
        business_type: Annotated[str | None, Form()] = None,
    ):
        try:
            content = await file.read(MAX_UPLOAD_BYTES + 1)
            return task_store.create_task(
                actor, file.filename or "", content, department, applicant,
                business_type=business_type,
            )
        finally:
            await file.close()

    @app.get("/api/v1/mock-pending")
    def list_mock_pending(actor: Annotated[User, Depends(require_roles("business"))]):
        _ = actor
        return {"items": [MOCK_PENDING_ITEM]}

    @app.post("/api/v1/mock-pending/{pending_id}/import", status_code=201)
    def import_mock_pending(
        pending_id: str,
        actor: Annotated[User, Depends(require_roles("business"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        if pending_id != MOCK_PENDING_ID:
            raise ApiError(404, "MOCK_PENDING_NOT_FOUND", "模拟待办不存在")
        return task_store.pending_imports.create(actor, fetch_pending_attachment)

    @app.post("/api/v1/tasks/{task_id}/documents", status_code=201)
    async def add_document_version(
        task_id: str,
        actor: Annotated[User, Depends(require_roles("business"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        base_document_version: Annotated[int, Form(ge=1)],
        file: Annotated[UploadFile, File()],
    ):
        try:
            content = await file.read(MAX_UPLOAD_BYTES + 1)
            return task_store.add_document_version(
                task_id, actor, base_document_version, file.filename or "", content
            )
        finally:
            await file.close()

    @app.get("/api/v1/tasks")
    def list_tasks(
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        machine_status: str | None = Query(default=None),
        legal_status: str | None = Query(default=None),
        writeback_status: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        risk_level: str | None = Query(default=None),
    ):
        return task_store.list_tasks(
            actor, machine_status, legal_status, writeback_status, limit, offset, risk_level
        )

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        return task_store.get_task(task_id, actor)

    @app.get("/api/v1/tasks/{task_id}/audit-events")
    def list_audit_events(
        task_id: str,
        actor: Annotated[User, Depends(require_roles("admin"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return task_store.list_audit_events(task_id, actor, document_version, limit, offset)

    @app.get("/api/v1/tasks/{task_id}/processing-records")
    def list_processing_records(
        task_id: str,
        actor: Annotated[User, Depends(require_roles("admin"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return task_store.list_processing_records(task_id, actor, document_version, limit, offset)

    @app.get("/api/v1/tasks/{task_id}/document")
    def get_parsed_document(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.get_parsed_document(task_id, actor, document_version)

    @app.get("/api/v1/tasks/{task_id}/document/preview")
    def get_document_preview(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
    ):
        content = task_store.get_pdf_preview(task_id, actor, document_version)
        return Response(
            content=content, media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": 'inline; filename="preview.pdf"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/tasks/{task_id}/risks")
    def get_rule_drafts(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
        review_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.get_rule_drafts(task_id, actor, document_version, review_version)

    @app.post("/api/v1/tasks/{task_id}/retry")
    def retry_rule_stage(
        task_id: str,
        payload: RetryRequest,
        actor: Annotated[User, Depends(require_roles("admin"))],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        attachment_retry = task_store.pending_imports.retry(
            task_id, payload.document_version, actor, fetch_pending_attachment)
        if attachment_retry is not None:
            return attachment_retry
        parsed_retry = task_store.jobs.retry_ocr(task_id, payload.document_version, actor)
        if parsed_retry is not None:
            return parsed_retry
        return task_store.rule_snapshots.retry(task_id, payload.document_version, actor)

    @app.get('/api/v1/tasks/{task_id}/attachment-attempts')
    def attachment_attempts(task_id: str,
        actor: Annotated[User, Depends(require_roles('admin'))],
        task_store: Annotated[TaskStore, Depends(get_task_store)]):
        return task_store.pending_imports.history(task_id, actor)

    @app.get("/api/v1/tasks/{task_id}/risks/snapshot")
    def get_rule_snapshot(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.get_rule_snapshot(task_id, actor, document_version)

    @app.get("/api/v1/tasks/{task_id}/model-result")
    def get_model_result(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.model_jobs.read(task_id, actor, document_version)

    @app.get("/api/v1/tasks/{task_id}/document/preview-map")
    def get_document_preview_map(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.previews.read(task_id, actor, document_version)[1]

    @app.get('/api/v1/tasks/{task_id}/review')
    def get_review(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
        document_version: int | None = Query(default=None, ge=1),
        review_version: int | None = Query(default=None, ge=1),
    ):
        return task_store.reviews.read(task_id, actor, document_version, review_version)

    @app.put('/api/v1/tasks/{task_id}/review')
    def save_review(
        task_id: str, payload: ReviewRequest,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        return task_store.reviews.save(task_id, actor, payload)

    @app.post('/api/v1/tasks/{task_id}/confirm')
    def confirm_review(
        task_id: str, payload: ConfirmRequest,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        return task_store.reviews.confirm(task_id, actor, payload)

    @app.get('/api/v1/mock-writeback-targets')
    def writeback_targets(actor: Annotated[User, Depends(require_roles('legal'))]):
        return {'items': [MOCK_PENDING_ITEM]}

    @app.post('/api/v1/tasks/{task_id}/mock-writeback')
    def submit_writeback(task_id: str, payload: WritebackRequest,
                         actor: Annotated[User, Depends(require_roles('legal'))],
                         task_store: Annotated[TaskStore, Depends(get_task_store)]):
        return task_store.writebacks.submit(task_id, actor, payload)

    @app.get('/api/v1/tasks/{task_id}/mock-writeback')
    def read_writeback(task_id: str, actor: Annotated[User, Depends(current_user)],
                       task_store: Annotated[TaskStore, Depends(get_task_store)],
                       review_version: int = Query(ge=1)):
        return task_store.writebacks.read(task_id, actor, review_version)

    @app.get('/api/v1/tasks/{task_id}/reports/status')
    def report_status(task_id: str, actor: Annotated[User, Depends(current_user)],
                      task_store: Annotated[TaskStore, Depends(get_task_store)],
                      review_version: int = Query(ge=1)):
        return task_store.reports.status(task_id, actor, review_version)

    @app.get('/api/v1/tasks/{task_id}/reports/{format}')
    def download_report(task_id: str, format: str, actor: Annotated[User, Depends(current_user)],
                        task_store: Annotated[TaskStore, Depends(get_task_store)],
                        review_version: int = Query(ge=1)):
        content = task_store.reports.download(task_id, actor, review_version, format)
        extension, media = ('md', 'text/markdown') if format == 'markdown' else ('pdf', 'application/pdf')
        return Response(content, media_type=media, headers={
            'Content-Disposition': f'inline; filename="review-{review_version}.{extension}"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.post('/api/v1/tasks/{task_id}/reports/{format}/retry')
    def retry_report(task_id: str, format: str, payload: ReportRetryRequest,
                     actor: Annotated[User, Depends(current_user)],
                     task_store: Annotated[TaskStore, Depends(get_task_store)]):
        return task_store.reports.retry(task_id, actor, payload.review_version, format)

    return app


app = create_app(auto_process_docx=True, auto_process_pdf=True, auto_process_ocr=True, auto_process_rules=True, auto_process_models=True,
                 auto_process_previews=True, auto_process_reports=True, auto_process_writebacks=True)
