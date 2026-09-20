import pytest
from sqlalchemy import text
from app.db.session import engine
@pytest.mark.asyncio
async def test_t02_tables_present(database):
    async with engine.connect() as conn:
        names=(await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
    for name in ('software','profiles','data_templates','template_versions','template_fields','source_snapshots','data_versions','performance_records','performance_record_versions','catalog_heads'):
        assert name in names
