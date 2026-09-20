from pydantic import BaseModel, Field
from typing import Any
class RecordCreateIn(BaseModel): stableKey: str; softwareId: str; profileId: str; templateVersionId: str; payload: dict[str,Any]={}
class RecordPatchIn(BaseModel): payload: dict[str,Any]; expectedRevision: int|None=None
class RecordOut(BaseModel): id: str; stableKey: str; softwareId: str; profileId: str; templateVersionId: str; ownerUserId: str; lifecycleStatus: str; revision: int; payload: dict[str,Any]; etag: str
class CatalogOut(BaseModel): dataVersionId: str|None; versionNo: int|None; records: list[dict[str,Any]]
