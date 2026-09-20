from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.core.request_id import RequestIdMiddleware
from app.core.errors import AppError, app_error_handler, generic_error_handler
from app.api.router import router

async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return a stable validation envelope without exposing input values."""
    weak = any("WEAK_PASSWORD" in str(error) for error in exc.errors())
    code = "WEAK_PASSWORD" if weak else "VALIDATION_ERROR"
    message = "密码至少8位且必须同时含字母和数字" if weak else "请求参数校验失败"
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(status_code=422, content={"error": {"code": code, "message": message, "requestId": rid}})

async def _seed_on_startup() -> None:
    """Idempotently ensure RBAC roles/permissions exist on boot.

    Guards against a fresh deployment that forgot to run the seed silently
    degrading every authenticated read to 403 (see outputs/viewer-403-investigation.md).
    ``seed()`` is existence-checked and idempotent, but it is *not* infallible:
    a database error would still propagate. Startup must not block, so any
    exception is logged (with traceback) and swallowed here rather than aborting
    boot. (This swallowing hid a real seed bug once -- see P5-B.)
    """
    try:
        from app.seed.seed_permissions import seed
        await seed()
    except Exception:
        import logging
        logging.getLogger("app").warning("startup RBAC seed skipped", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _seed_on_startup()
    yield


def create_app() -> FastAPI:
    s=get_settings(); configure_logging(); app=FastAPI(title=s.app_name,version=s.app_version,lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware); app.add_middleware(CORSMiddleware,allow_origins=s.cors_origin_list,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
    app.add_exception_handler(AppError,app_error_handler); app.add_exception_handler(RequestValidationError,validation_error_handler); app.add_exception_handler(Exception,generic_error_handler); app.include_router(router)
    return app
app=create_app()
