"""Public API errors without sensitive request details."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "retryable": exc.retryable},
    )


def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "INVALID_REQUEST", "message": "请求格式不正确", "retryable": False},
    )
