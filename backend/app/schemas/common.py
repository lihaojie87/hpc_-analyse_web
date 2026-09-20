from pydantic import BaseModel
class ErrorOut(BaseModel): error: dict
class HealthOut(BaseModel): status: str; components: dict | None = None
class VersionOut(BaseModel): appName: str; version: str; env: str
