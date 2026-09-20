import contextvars, uuid
from starlette.middleware.base import BaseHTTPMiddleware
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"
        request_id_var.set(rid); request.state.request_id=rid
        response = await call_next(request); response.headers["X-Request-ID"] = rid
        return response
