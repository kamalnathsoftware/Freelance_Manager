import logging

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import install_error_handlers
from app.core.ratelimit import RateLimitMiddleware

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)


def create_app() -> FastAPI:
    s = get_settings()
    if s.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=s.sentry_dsn, environment=s.environment)
        except ImportError:
            logging.getLogger(__name__).warning("SENTRY_DSN set but sentry-sdk not installed")

    app = FastAPI(
        title=s.app_name, version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)

    @app.middleware("http")
    async def public_cors(request: Request, call_next):  # type: ignore[no-untyped-def]
        # The embeddable chat widget runs on arbitrary customer sites: allow any origin, but only on
        # /public/* and never with credentials (it authenticates with a per-visitor token header).
        if request.url.path.startswith("/api/v1/public/"):
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type, X-Visitor-Token",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            }
            if request.method == "OPTIONS":
                return Response(status_code=204, headers=headers)
            response = await call_next(request)
            response.headers.update(headers)
            return response
        return await call_next(request)

    app.include_router(v1_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        db = "ok"
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            db = "down"
        return {"status": "ok" if db == "ok" else "degraded", "db": db}

    return app


app = create_app()
