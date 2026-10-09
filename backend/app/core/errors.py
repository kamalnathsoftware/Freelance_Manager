"""Consistent error format: {"error": {"code", "message", "details"}}."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def _body(code: str, message: str, details: object = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict | list):  # structured detail (e.g. per-field form errors)
            return JSONResponse(
                _body(f"http_{exc.status_code}", "Request failed", exc.detail),
                status_code=exc.status_code,
                headers=exc.headers,
            )
        return JSONResponse(
            _body(f"http_{exc.status_code}", str(exc.detail)),
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Invalid request", details), status_code=422)
