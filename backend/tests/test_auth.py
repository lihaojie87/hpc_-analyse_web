import pytest
from app.core.rate_limit import limiter

@pytest.mark.asyncio
async def test_register_login_refresh_logout_change_password(client):
    r=await client.post('/api/v1/auth/register',json={'username':'alice','password':'Alice1234','email':'alice@example.com'})
    assert r.status_code==201; data=r.json(); assert data['user']['roles']==['viewer']; assert 'data:read' in data['user']['permissions']; assert 'password_hash' not in str(data)
    access,refresh=data['accessToken'],data['refreshToken']
    r=await client.post('/api/v1/auth/login',json={'username':'alice','password':'badpass1'}); assert r.status_code==401
    r=await client.post('/api/v1/auth/login',json={'username':'alice','password':'Alice1234'}); assert r.status_code==200; data=r.json(); refresh=data['refreshToken']
    r=await client.post('/api/v1/auth/refresh',json={'refreshToken':refresh}); assert r.status_code==200; rotated=r.json()['refreshToken']; assert rotated!=refresh
    r=await client.post('/api/v1/auth/refresh',json={'refreshToken':refresh}); assert r.status_code==401
    access=r.json() if False else data['accessToken']
    r=await client.post('/api/v1/auth/logout-all',headers={'Authorization':f'Bearer {access}'}); assert r.status_code==200
    r=await client.post('/api/v1/auth/change-password',headers={'Authorization':f'Bearer {access}'},json={'oldPassword':'Alice1234','newPassword':'weak'}); assert r.status_code==422; assert r.json()['error']['code']=='WEAK_PASSWORD'
    r=await client.post('/api/v1/auth/change-password',headers={'Authorization':f'Bearer {access}'},json={'oldPassword':'Alice1234','newPassword':'Alice5678'}); assert r.status_code==200

@pytest.mark.asyncio
async def test_auth_required_and_lockout(client):
    r=await client.get('/api/v1/auth/me'); assert r.status_code==401; assert r.json()['error']['code']=='AUTH_REQUIRED'
    await client.post('/api/v1/auth/register',json={'username':'locked','password':'Locked123'})
    for _ in range(5): await client.post('/api/v1/auth/login',json={'username':'locked','password':'wrong1'})
    r=await client.post('/api/v1/auth/login',json={'username':'locked','password':'Locked123'}); assert r.status_code==423

@pytest.mark.asyncio
async def test_rate_limit(client):
    limiter._events.clear(); limiter.max_attempts=2
    await client.post('/api/v1/auth/login',json={'username':'none','password':'Wrong123'})
    await client.post('/api/v1/auth/login',json={'username':'none','password':'Wrong123'})
    r=await client.post('/api/v1/auth/login',json={'username':'none','password':'Wrong123'}); assert r.status_code==429
    limiter.max_attempts=10
