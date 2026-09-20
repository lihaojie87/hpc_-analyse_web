"""Server-sent events for catalog publication notifications."""
import asyncio
from typing import AsyncIterator
from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.deps.auth_deps import require_permission
from app.services.event_service import dispatch_pending, get_broker, sse_message

router = APIRouter(prefix="/events")


@router.get("/stream")
async def stream_events(
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user=Depends(require_permission("data:read")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream publication metadata; clients re-query catalog data with their token."""
    await dispatch_pending(db)

    async def body() -> AsyncIterator[str]:
        event_broker = await get_broker()
        async for event in event_broker.subscribe(last_event_id):
            yield sse_message(event)
            await asyncio.sleep(0)

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
