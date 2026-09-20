from pydantic import BaseModel, Field
from typing import Any
class TemplateFieldIn(BaseModel):
    path: str = Field(min_length=1,max_length=255); label: str; dataType: str; unit: str|None=None; required: bool=False; rules: dict[str,Any]={}; sourceMapping: dict[str,Any]={}; ordinal: int=Field(0,ge=0)
class TemplateCreateIn(BaseModel): code: str; name: str; description: str|None=None; fields: list[TemplateFieldIn]=[]
class TemplateVersionIn(BaseModel): schemaJson: dict[str,Any]={}; fields: list[TemplateFieldIn]=[]
class TemplateFieldOut(BaseModel): id: str; path: str; label: str; dataType: str; unit: str|None; required: bool; rules: dict[str,Any]; sourceMapping: dict[str,Any]; ordinal: int
class TemplateVersionOut(BaseModel): id: str; templateId: str; versionNo: int; status: str; revision: int; schemaJson: dict[str,Any]; fields: list[TemplateFieldOut]=[]
class TemplateOut(BaseModel): id: str; code: str; name: str; description: str|None; status: str; revision: int; currentVersionId: str|None=None
