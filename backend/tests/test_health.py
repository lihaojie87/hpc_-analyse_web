import pytest
from sqlalchemy import text
from app.db.session import SessionLocal

@pytest.mark.asyncio
async def test_live_ready_version(client):
    r=await client.get('/health/live'); assert r.status_code==200 and r.json()['status']=='ok'
    r=await client.get('/health/ready'); assert r.status_code in (200,503); assert 'db' in r.json()['components']
    r=await client.get('/api/v1/version'); assert set(r.json())=={'appName','version','env'}

@pytest.mark.asyncio
async def test_sensitive_response_scan(client):
    secret='test-secret-not-for-production'
    r=await client.post('/api/v1/auth/register',json={'username':'scan','password':'Scan1234'})
    assert secret not in r.text and 'password_hash' not in r.text
    r=await client.get('/api/v1/auth/me'); assert secret not in r.text
