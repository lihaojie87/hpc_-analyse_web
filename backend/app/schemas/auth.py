from pydantic import BaseModel, Field, field_validator
import re
class RegisterIn(BaseModel):
    username: str = Field(min_length=3,max_length=64); password: str; email: str|None=None; displayName: str|None=None
    @field_validator("password")
    @classmethod
    def strong(cls,v: str)->str:
        if len(v)<8 or not re.search(r"[A-Za-z]",v) or not re.search(r"\d",v): raise ValueError("WEAK_PASSWORD")
        return v
class LoginIn(BaseModel): username: str; password: str
class RefreshIn(BaseModel): refreshToken: str
class ChangePasswordIn(BaseModel): oldPassword: str; newPassword: str
class TokenPair(BaseModel): accessToken: str; refreshToken: str; tokenType: str="bearer"; expiresIn: int
class AuthResponse(BaseModel): user: dict; accessToken: str; refreshToken: str; tokenType: str="bearer"; expiresIn: int
