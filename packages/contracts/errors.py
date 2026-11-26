from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from packages.observability.logging import get_correlation_id


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_AUTHORISED = "NOT_AUTHORISED"
    NOT_FOUND = "NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    INTEGRATION_REJECTED = "INTEGRATION_REJECTED"


class ApiErrorResponse(BaseModel):
    error_code: ErrorCode
    message: str
    correlation_id: str
    details: Optional[dict[str, Any]] = None


class DomainError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        body = ApiErrorResponse(
            error_code=exc.code,
            message=exc.message,
            correlation_id=get_correlation_id(),
            details=exc.details,
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump())

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        body = ApiErrorResponse(
            error_code=ErrorCode.DEPENDENCY_UNAVAILABLE,
            message="An unexpected error occurred. Quote the correlation_id for support.",
            correlation_id=get_correlation_id(),
        )
        return JSONResponse(status_code=500, content=body.model_dump())
