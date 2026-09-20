from datetime import datetime, timezone
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import DataVersion,CatalogHead,PerformanceRecord,PerformanceRecordVersion
from app.services.event_service import enqueue_publish_event
from app.core.errors import AppError,ErrorCode
import hashlib,json
async def create_staging(db,actor,records):
    if not records: raise AppError(ErrorCode.VALIDATION_ERROR,'空批次不可发布')
    n=(await db.execute(select(func.max(DataVersion.version_no)))).scalar_one_or_none() or 0
    dv=DataVersion(version_no=n+1,checksum=hashlib.sha256(json.dumps(records,sort_keys=True,default=str).encode()).hexdigest(),record_count=len(records),created_by=actor.id); db.add(dv); await db.flush()
    for r in records: db.add(PerformanceRecordVersion(record_id=r.id,data_version_id=dv.id,record_revision=r.revision,raw_payload=r.draft_payload,parsed_payload=r.draft_payload,derived_payload={}))
    await db.commit(); return dv
async def approve(db:AsyncSession,dv:DataVersion|None,actor):
    if not dv: raise AppError(ErrorCode.NOT_FOUND,'数据版本不存在')
    if dv.created_by==actor.id: raise AppError(ErrorCode.FORBIDDEN,'提交者不能自审')
    if dv.status!='staging' or dv.record_count<1: raise AppError(ErrorCode.CONFLICT,'版本状态或快照不完整')
    dv.status='approved'; dv.approved_by=actor.id; dv.approved_at=datetime.now(timezone.utc).replace(tzinfo=None); await db.commit(); return dv
async def publish(db:AsyncSession,dv:DataVersion|None,actor,expected_head_revision:int,*,rollback_operation:bool=False):
    if not dv: raise AppError(ErrorCode.NOT_FOUND,'数据版本不存在')
    if dv.created_by==actor.id and not rollback_operation: raise AppError(ErrorCode.FORBIDDEN,'提交者不能自发布')
    if dv.status!='approved' or dv.record_count<1: raise AppError(ErrorCode.CONFLICT,'版本未审核或快照不完整')
    head=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog').with_for_update())).scalar_one_or_none()
    if not head: raise AppError(ErrorCode.CONFLICT,'CatalogHead 未初始化')
    if head.current_revision!=expected_head_revision: raise AppError(ErrorCode.PRECONDITION_FAILED,'current版本已变化')
    dv.status='published'; dv.published_by=actor.id; dv.published_at=datetime.now(timezone.utc).replace(tzinfo=None); head.current_version_id=dv.id; head.current_revision+=1; head.updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
    await enqueue_publish_event(db, dv.id, dv.version_no, dv.published_at)
    await db.commit(); return dv
async def rollback(db:AsyncSession,target_version_id:str,actor,expected_head_revision:int):
    target=(await db.execute(select(DataVersion).where(DataVersion.id==target_version_id,DataVersion.status=='published'))).scalar_one_or_none()
    if not target: raise AppError(ErrorCode.NOT_FOUND,'目标发布版本不存在')
    snapshots=(await db.execute(select(PerformanceRecordVersion).where(PerformanceRecordVersion.data_version_id==target.id))).scalars().all()
    records=[]
    for snap in snapshots:
        record=(await db.execute(select(PerformanceRecord).where(PerformanceRecord.id==snap.record_id))).scalar_one_or_none()
        if record: records.append((record,snap))
    if not records: raise AppError(ErrorCode.VALIDATION_ERROR,'目标版本无可回滚快照')
    count=(await db.execute(select(func.max(DataVersion.version_no)))).scalar_one_or_none() or 0
    checksum=hashlib.sha256(json.dumps([s.parsed_payload for _,s in records],sort_keys=True,default=str).encode()).hexdigest()
    new=DataVersion(version_no=count+1,revision=1,status='approved',checksum=checksum,record_count=len(records),created_by=actor.id,approved_by=actor.id,approved_at=datetime.now(timezone.utc).replace(tzinfo=None)); db.add(new); await db.flush()
    for record,snap in records: db.add(PerformanceRecordVersion(record_id=record.id,data_version_id=new.id,record_revision=snap.record_revision,raw_payload=snap.raw_payload,parsed_payload=snap.parsed_payload,derived_payload=snap.derived_payload,source_snapshot_id=snap.source_snapshot_id,source_locator=snap.source_locator))
    await db.flush()
    return await publish(db,new,actor,expected_head_revision,rollback_operation=True)
async def get_current(db:AsyncSession):
    head=(await db.execute(select(CatalogHead).where(CatalogHead.scope_key=='performance_catalog'))).scalar_one_or_none()
    if not head or not head.current_version_id: return {'dataVersionId':None,'versionNo':None,'records':[]}
    dv=(await db.execute(select(DataVersion).where(DataVersion.id==head.current_version_id,DataVersion.status=='published'))).scalar_one_or_none()
    if not dv: raise AppError(ErrorCode.INTERNAL_ERROR,'current 指向无效版本')
    snapshots=(await db.execute(select(PerformanceRecordVersion).where(PerformanceRecordVersion.data_version_id==dv.id))).scalars().all()
    return {'dataVersionId':dv.id,'versionNo':dv.version_no,'publishedAt':dv.published_at.isoformat()+'Z' if dv.published_at else None,'records':[{'recordId':s.record_id,'recordRevision':s.record_revision,'rawPayload':s.raw_payload,'parsedPayload':s.parsed_payload,'derivedPayload':s.derived_payload} for s in snapshots]}
