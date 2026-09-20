import pytest
from sqlalchemy import inspect
from app.db.session import engine

@pytest.mark.asyncio
async def test_t04_source_snapshot_has_fk_and_tombstone(database):
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        columns = await connection.run_sync(lambda c: {x['name'] for x in inspect(c).get_columns('source_snapshots')})
        foreign_keys = await connection.run_sync(lambda c: inspect(c).get_foreign_keys('source_snapshots'))
    assert 'data_sources' in tables and 'tombstone' in columns
    assert any('data_sources' == fk['referred_table'] for fk in foreign_keys)
