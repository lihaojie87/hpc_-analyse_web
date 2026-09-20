import hashlib, uuid
from datetime import datetime, timezone, timedelta
import bcrypt, jwt
from app.core.config import get_settings

def hash_password(password: str) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def verify_password(password: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError): return False
def _encode(sub: str, typ: str, ttl: int, jti: str|None=None) -> str:
    now=datetime.now(timezone.utc); payload={"sub":sub,"type":typ,"iat":now,"exp":now+timedelta(seconds=ttl)}
    if jti: payload["jti"]=jti
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
def create_token_pair(user_id: str) -> tuple[str,str,str,datetime]:
    s=get_settings(); jti=str(uuid.uuid4()); exp=datetime.now(timezone.utc)+timedelta(seconds=s.jwt_refresh_ttl)
    return _encode(user_id,"access",s.jwt_access_ttl), _encode(user_id,"refresh",s.jwt_refresh_ttl,jti), jti, exp.replace(tzinfo=None)
def decode_token(token: str) -> dict: return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
def hash_refresh_token(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()
