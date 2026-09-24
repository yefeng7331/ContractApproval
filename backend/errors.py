"""Public API errors without sensitive request details."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        *,
        task_id: str | None = None,
        current_status: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.task_id = task_id
        self.current_status = current_status


def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    content = {"code": exc.code, "message": exc.message, "retryable": exc.retryable}
    if exc.task_id is not None:
        content["task_id"] = exc.task_id
    if exc.current_status is not None:
        content["current_status"] = exc.current_status
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "INVALID_REQUEST", "message": "请求格式不正确", "retryable": False},
    )
