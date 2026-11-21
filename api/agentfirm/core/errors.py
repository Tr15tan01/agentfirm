"""Typed application errors rendered as RFC 9457 problem details."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, detail: str | None = None, *, code: str | None = None) -> None:
        super().__init__(detail or self.__class__.__name__)
        self.detail = detail or "Request could not be processed."
        if code:
            self.code = code


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


class NotFound(AppError):
    """Also used for resources in another organisation, so existence never leaks."""

    status = 404
    code = "not_found"


class Conflict(AppError):
    status = 409
    code = "conflict"


class Unprocessable(AppError):
    status = 422
    code = "unprocessable"


class PaymentRequired(AppError):
    """Plan limits: out of credits, or a feature the plan doesn't include."""

    status = 402
    code = "payment_required"


class TooManyRequests(AppError):
    status = 429
    code = "rate_limited"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            media_type="application/problem+json",
            content={"type": f"https://agentfirm.app/errors/{exc.code}", "title": exc.code, "status": exc.status, "detail": exc.detail},
        )
