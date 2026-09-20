"""Auto-resolve Feishu tenant access token from app credentials in config."""
import time as _time
import httpx
from app.core.config import get_settings


_cache: dict = {"token": None, "expires_at": 0}


async def get_feishu_token() -> str:
    """Return a valid tenant access token, refreshing when expired.

    Uses HPC_FEISHU_APP_ID / HPC_FEISHU_APP_SECRET from settings.
    Token is cached in-process for the duration of its TTL (minus 60s margin).
    """
    now = _time.time()
    if _cache["token"] and _cache["expires_at"] > now + 60:
        return _cache["token"]

    settings = get_settings()
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise RuntimeError(
            "飞书凭证未配置，请设置 HPC_FEISHU_APP_ID / HPC_FEISHU_APP_SECRET 环境变量"
        )

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书 token 获取失败: {data.get('msg', 'unknown error')}")

    _cache["token"] = data["tenant_access_token"]
    _cache["expires_at"] = now + data.get("expire", 7200)
    return _cache["token"]