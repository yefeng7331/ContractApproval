"""HTTP entry point for the local demo backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Callable

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from backend.auth import AuthStore, User
from backend.errors import ApiError, api_error_handler, validation_error_handler
from backend.tasks import MAX_UPLOAD_BYTES, TaskStore


bearer_scheme = HTTPBearer(auto_error=False)


def default_database_path() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "contract_approval.sqlite3"


def default_upload_root() -> Path:
    return Path(__file__).resolve().parents[1] / "storage" / "uploads"


class LoginRequest(BaseModel):
    username: str
    password: str = Field(repr=False)


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
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = auth_store or AuthStore(database_path or default_database_path())
        store.initialize()
        task_store = TaskStore(store, upload_root or default_upload_root())
        task_store.initialize()
        app.state.auth_store = store
        app.state.task_store = task_store
        try:
            yield
        finally:
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
    ):
        try:
            content = await file.read(MAX_UPLOAD_BYTES + 1)
            return task_store.create_task(
                actor, file.filename or "", content, department, applicant
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
    ):
        return task_store.list_tasks(
            actor, machine_status, legal_status, writeback_status, limit, offset
        )

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(
        task_id: str,
        actor: Annotated[User, Depends(current_user)],
        task_store: Annotated[TaskStore, Depends(get_task_store)],
    ):
        return task_store.get_task(task_id, actor)

    return app


app = create_app()
