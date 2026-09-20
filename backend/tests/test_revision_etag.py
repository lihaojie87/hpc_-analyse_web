import pytest
from app.core.errors import AppError
from app.services.catalog_service import update_record
@pytest.mark.asyncio
async def test_revision_conflict(db):
    class R: owner_user_id='u'; revision=2; lifecycle_status='draft'
    class Actor: id='u'
    class P: payload={'v':1}
    with pytest.raises(AppError) as exc: await update_record(db,R(),P(),Actor(),1)
    assert exc.value.code.value=='CONFLICT'
