import pytest
from app.services.audit_service import append
@pytest.mark.asyncio
async def test_audit_sanitizes_sensitive(db):
    event=await append(db,actor_id=None,action='test',before={'password':'secret','safe':1},after={'refreshToken':'raw'},request_id='req')
    assert event.before_json['password']=='[REDACTED]' and event.after_json['refreshToken']=='[REDACTED]'
