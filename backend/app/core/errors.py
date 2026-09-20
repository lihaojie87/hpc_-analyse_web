from enum import Enum
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette import status

class ErrorCode(str, Enum):
    VALIDATION_ERROR="VALIDATION_ERROR"; AUTH_REQUIRED="AUTH_REQUIRED"; AUTH_INVALID_CREDENTIALS="AUTH_INVALID_CREDENTIALS"
    AUTH_TOKEN_EXPIRED="AUTH_TOKEN_EXPIRED"; AUTH_TOKEN_INVALID="AUTH_TOKEN_INVALID"; AUTH_TOKEN_REVOKED="AUTH_TOKEN_REVOKED"
    ACCOUNT_LOCKED="ACCOUNT_LOCKED"; RATE_LIMITED="RATE_LIMITED"; FORBIDDEN="FORBIDDEN"; NOT_FOUND="NOT_FOUND"
    CONFLICT="CONFLICT"; USER_EXISTS="USER_EXISTS"; WEAK_PASSWORD="WEAK_PASSWORD"; PRECONDITION_REQUIRED="PRECONDITION_REQUIRED"; PRECONDITION_FAILED="PRECONDITION_FAILED"; INTERNAL_ERROR="INTERNAL_ERROR"

_STATUS = {ErrorCode.PRECONDITION_FAILED:412,ErrorCode.PRECONDITION_REQUIRED:428,ErrorCode.AUTH_REQUIRED:401,ErrorCode.AUTH_INVALID_CREDENTIALS:401,ErrorCode.AUTH_TOKEN_EXPIRED:401,ErrorCode.AUTH_TOKEN_INVALID:401,ErrorCode.AUTH_TOKEN_REVOKED:401,ErrorCode.ACCOUNT_LOCKED:423,ErrorCode.RATE_LIMITED:429,ErrorCode.FORBIDDEN:403,ErrorCode.NOT_FOUND:404,ErrorCode.CONFLICT:409,ErrorCode.USER_EXISTS:409,ErrorCode.WEAK_PASSWORD:422,ErrorCode.VALIDATION_ERROR:422}
class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, http_status: int | None = None):
        super().__init__(message); self.code=code; self.message=message; self.http_status=http_status or _STATUS.get(code,500)

def error_response(request: Request, exc: AppError) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(status_code=exc.http_status, content={"error":{"code":exc.code.value,"message":exc.message,"requestId":rid}})

async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(request, exc)

async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, AppError(ErrorCode.INTERNAL_ERROR, "服务器内部错误", 500))
