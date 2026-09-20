import pytest
from app.deps.auth_deps import require_review_authorization
from app.core.errors import AppError

@pytest.mark.asyncio
async def test_viewer_forbidden_user_manage(client):
    await client.post('/api/v1/auth/register',json={'username':'viewer1','password':'Viewer123'})
    login=(await client.post('/api/v1/auth/login',json={'username':'viewer1','password':'Viewer123'})).json()
    r=await client.get('/api/v1/users',headers={'Authorization':f"Bearer {login['accessToken']}"})
    assert r.status_code==403 and r.json()['error']['code']=='FORBIDDEN'

@pytest.mark.asyncio
async def test_viewer_forbidden_templates(client):
    """Regression guard: template listing now accepts template:read OR
    template:manage, but viewer holds neither, so it must still get 403."""
    await client.post('/api/v1/auth/register',json={'username':'viewer2','password':'Viewer123'})
    login=(await client.post('/api/v1/auth/login',json={'username':'viewer2','password':'Viewer123'})).json()
    r=await client.get('/api/v1/templates',headers={'Authorization':f"Bearer {login['accessToken']}"})
    assert r.status_code==403 and r.json()['error']['code']=='FORBIDDEN'

@pytest.mark.asyncio
async def test_review_self_rejected(db):
    class Actor: id='owner-1'
    dep=require_review_authorization('owner-1')
    with pytest.raises(AppError) as error:
        await dep(user=Actor(), db=db)
    assert error.value.code.value == 'FORBIDDEN'

@pytest.mark.asyncio
async def test_admin_can_assign_provider(client):
    login=(await client.post('/api/v1/auth/login',json={'username':'admin','password':'Admin1234'})).json()
    await client.post('/api/v1/auth/register',json={'username':'provider1','password':'Provider123'})
    users=(await client.get('/api/v1/users',headers={'Authorization':f"Bearer {login['accessToken']}"})).json()['items']
    uid=next(x['id'] for x in users if x['username']=='provider1')
    r=await client.post(f'/api/v1/users/{uid}/roles',headers={'Authorization':f"Bearer {login['accessToken']}"},json={'roleCode':'provider'})
    assert r.status_code==200 and 'provider' in r.json()['roles']
