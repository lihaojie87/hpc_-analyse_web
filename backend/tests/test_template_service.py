import pytest
from app.schemas.template import TemplateCreateIn,TemplateFieldIn
from app.services.template_service import create_template,publish_version
@pytest.mark.asyncio
async def test_template_draft_publish_freezes(db):
    class Actor: id='template-owner'
    t,v=await create_template(db,TemplateCreateIn(code='svc-t',name='Svc',fields=[TemplateFieldIn(path='x',label='X',dataType='number')]),Actor())
    assert v.status=='draft'; v=await publish_version(db,v.id,Actor()); assert v.status=='published'
