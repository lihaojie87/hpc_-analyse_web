"""Analytics overview endpoint for the dashboard."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.db.session import get_db
from app.deps.auth_deps import get_current_user
from app.db.models import (
    PerformanceRecord,
    Software,
    Profile,
    DataTemplate,
    ImportJob,
    DataSource,
    User,
)

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview")
async def analytics_overview(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return dashboard analytics: counts, status distribution, import summary."""

    # Total counts
    sw_count = (await db.execute(select(func.count(Software.id)))).scalar() or 0
    profile_count = (await db.execute(select(func.count(Profile.id)))).scalar() or 0
    template_count = (await db.execute(select(func.count(DataTemplate.id)))).scalar() or 0
    source_count = (await db.execute(select(func.count(DataSource.id)))).scalar() or 0
    user_count = (await db.execute(
        select(func.count(User.id)).where(User.is_active.is_(True))
    )).scalar() or 0

    # Record counts by lifecycle status
    status_counts = {}
    status_rows = (
        await db.execute(
            select(
                PerformanceRecord.lifecycle_status,
                func.count(PerformanceRecord.id),
            )
            .where(PerformanceRecord.deleted.is_(False))
            .group_by(PerformanceRecord.lifecycle_status)
        )
    ).all()
    for status, cnt in status_rows:
        status_counts[status] = cnt

    total_records = sum(status_counts.values())

    # Software with most records (top 10), with names
    top_sw_rows = (
        await db.execute(
            select(
                Software.code,
                Software.name,
                func.count(PerformanceRecord.id).label("cnt"),
            )
            .join(PerformanceRecord, PerformanceRecord.software_id == Software.id)
            .where(PerformanceRecord.deleted.is_(False))
            .group_by(Software.id)
            .order_by(func.count(PerformanceRecord.id).desc())
            .limit(10)
        )
    ).all()

    top_software = [
        {"code": sw_code, "name": sw_name, "count": cnt}
        for sw_code, sw_name, cnt in top_sw_rows
    ]

    # Import job summary
    import_status_counts = {}
    import_rows = (
        await db.execute(
            select(
                ImportJob.status,
                func.count(ImportJob.id),
            ).group_by(ImportJob.status)
        )
    ).all()
    for status, cnt in import_rows:
        import_status_counts[status] = cnt

    total_imports = sum(import_status_counts.values())

    return {
        "counts": {
            "software": sw_count,
            "profiles": profile_count,
            "templates": template_count,
            "dataSources": source_count,
            "users": user_count,
            "totalRecords": total_records,
        },
        "recordStatus": status_counts,
        "topSoftware": top_software,
        "importStatus": import_status_counts,
        "totalImports": total_imports,
    }