from pydantic import BaseModel
class DataVersionOut(BaseModel): id: str; versionNo: int; revision: int; status: str; checksum: str; recordCount: int; publishedAt: str|None=None
class PublishIn(BaseModel): expectedHeadRevision: int=0
class RollbackIn(BaseModel): expectedHeadRevision: int=0
class AuditOut(BaseModel): id: str; action: str; targetType: str|None; targetId: str|None; requestId: str; targetRevision: int|None; outcome: str; createdAt: str
