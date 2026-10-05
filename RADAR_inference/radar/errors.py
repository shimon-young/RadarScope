"""统一错误模型。

所有对外错误响应都必须是 `schemas.ErrorBody` 的 JSON 形态（契约第 1.3 节），
不允许出现 FastAPI 默认的 `{"detail": ...}`。
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .schemas import ErrorBody, ErrorCode

# 契约规定的 HTTP 映射
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: status.HTTP_400_BAD_REQUEST,
    ErrorCode.INVALID_IMAGE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.PAYLOAD_TOO_LARGE: getattr(
        status, "HTTP_413_CONTENT_TOO_LARGE", status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    ),
    ErrorCode.UNSUPPORTED_MEDIA: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.INSUFFICIENT_STORAGE: status.HTTP_507_INSUFFICIENT_STORAGE,
    ErrorCode.WEIGHTS_MISSING: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.CANCELLED: status.HTTP_409_CONFLICT,
    ErrorCode.UNAUTHORIZED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.INTERNAL: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class AppError(Exception):
    """业务错误。code 取自 ErrorCode，HTTP 状态由映射表决定。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        detail: dict[str, Any] | None = None,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.retryable = retryable
        self._http_status = http_status

    @property
    def http_status(self) -> int:
        return self._http_status or HTTP_STATUS[self.code]

    def body(self, request: Request) -> ErrorBody:
        return ErrorBody(
            code=self.code,
            message=self.message,
            detail=self.detail,
            request_id=getattr(request.state, "request_id", None),
            retryable=self.retryable,
        )


class JobCancelled(AppError):
    """任务被协作式取消——由推理内核在检查点抛出。"""

    def __init__(self, message: str = "任务已取消") -> None:
        super().__init__(ErrorCode.CANCELLED, message)


async def _render(request: Request, payload: ErrorBody, http_status: int) -> JSONResponse:
    return JSONResponse(status_code=http_status, content=payload.model_dump(mode="json"))


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return await _render(request, exc.body(request), exc.http_status)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    body = ErrorBody(
        code=ErrorCode.BAD_REQUEST,
        message="请求参数不合法",
        detail={"errors": exc.errors()[:10]},
        retryable=False,
    )
    return await _render(request, body, status.HTTP_400_BAD_REQUEST)


async def unhandled_error_handler(request: Request, _exc: Exception) -> JSONResponse:
    body = ErrorBody(
        code=ErrorCode.INTERNAL,
        message="服务内部错误",
        detail=None,
        retryable=False,
    )
    return await _render(request, body, status.HTTP_500_INTERNAL_SERVER_ERROR)
