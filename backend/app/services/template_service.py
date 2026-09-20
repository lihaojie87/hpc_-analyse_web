from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import DataTemplate,TemplateVersion,TemplateField
from app.core.errors import AppError,ErrorCode
from app.core.security import hash_refresh_token
from datetime import datetime, timezone
import uuid
async def create_template(db:AsyncSession,payload,actor):
    if (await db.execute(select(DataTemplate).where(DataTemplate.code==payload.code))).scalar_one_or_none(): raise AppError(ErrorCode.CONFLICT,'模板编码已存在')
    t=DataTemplate(code=payload.code,name=payload.name,description=payload.description,created_by=actor.id); db.add(t); await db.flush(); v=TemplateVersion(template_id=t.id,version_no=1,schema_json={},created_by=actor.id); db.add(v); await db.flush()
    for f in payload.fields: db.add(TemplateField(template_version_id=v.id,path=f.path,label=f.label,data_type=f.dataType,unit=f.unit,required=f.required,rules_json=f.rules,source_mapping_json=f.sourceMapping,ordinal=f.ordinal))
    await db.commit(); return t,v
async def create_version(db,template_id,payload,actor):
    t=(await db.execute(select(DataTemplate).where(DataTemplate.id==template_id))).scalar_one_or_none()
    if not t: raise AppError(ErrorCode.NOT_FOUND,'模板不存在')
    n=(await db.execute(select(TemplateVersion.version_no).where(TemplateVersion.template_id==template_id).order_by(TemplateVersion.version_no.desc()))).scalars().first() or 0
    v=TemplateVersion(template_id=template_id,version_no=n+1,schema_json=payload.schemaJson,created_by=actor.id); db.add(v); await db.flush()
    for f in payload.fields: db.add(TemplateField(template_version_id=v.id,path=f.path,label=f.label,data_type=f.dataType,unit=f.unit,required=f.required,rules_json=f.rules,source_mapping_json=f.sourceMapping,ordinal=f.ordinal))
    await db.commit(); return v
async def publish_version(db,version_id,actor):
    v=(await db.execute(select(TemplateVersion).where(TemplateVersion.id==version_id))).scalar_one_or_none()
    if not v: raise AppError(ErrorCode.NOT_FOUND,'模板版本不存在')
    if v.status!='draft': raise AppError(ErrorCode.CONFLICT,'模板版本不可发布')
    if not (await db.execute(select(TemplateField).where(TemplateField.template_version_id==v.id))).scalars().first(): raise AppError(ErrorCode.VALIDATION_ERROR,'模板必须包含字段')
    v.status='published'; v.published_by=actor.id; v.published_at=datetime.now(timezone.utc).replace(tzinfo=None); await db.commit(); return v
