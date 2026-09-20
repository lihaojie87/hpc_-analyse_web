"""Worker entry point kept broker-agnostic for T05 worker selection."""
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.import_service import ImportService

async def run_import_job(db: AsyncSession, service: ImportService, job_id: str, records: list[dict]) -> object:
    """Execute validated staging work in a worker transaction."""
    return await service.create_staging(db, job_id, records)
