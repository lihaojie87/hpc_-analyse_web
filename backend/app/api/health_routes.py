from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.db.session import SessionLocal
from app.core.config import get_settings
router=APIRouter()
@router.get("/health/live")
async def live(): return {"status":"ok"}
@router.get("/health/ready")
async def ready():
    dbok=True
    try:
        async with SessionLocal() as s: await s.execute(text("SELECT 1"))
    except Exception: dbok=False
    data={"status":"ok" if dbok else "degraded","components":{"api":"ok","db":"ok" if dbok else "fail","redis":"fail"}}
    return JSONResponse(status_code=200 if dbok else 503,content=data)
@router.get("/api/v1/version")
async def version():
    s=get_settings(); return {"appName":s.app_name,"version":s.app_version,"env":s.env}
