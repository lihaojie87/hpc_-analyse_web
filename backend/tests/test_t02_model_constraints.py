import pytest
from sqlalchemy import select
from app.db.models import Software,DataTemplate,TemplateVersion,CatalogHead
@pytest.mark.asyncio
async def test_t02_tables_and_catalog_head(db):
    db.add(Software(code='t02-soft',name='T02')); db.add(DataTemplate(code='t02-template',name='T02'))
    await db.commit(); assert (await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one().current_revision==0
