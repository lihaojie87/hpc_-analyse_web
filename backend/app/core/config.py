from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "HPC Performance Platform"
    app_version: str = "0.1.0"
    env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./hpc.db"
    test_database_url: str = "sqlite+aiosqlite:///./test.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str
    jwt_access_ttl: int = 900
    jwt_refresh_ttl: int = 604800
    cors_origins: str = "http://localhost:5173"
    login_max_failures: int = 5
    login_lock_seconds: int = 900
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None
    # Feishu Open Platform credentials for automatic token resolution.
    # When both are configured, the import flow auto-acquires a tenant
    # access token so users only need to provide a spreadsheet URL.
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    model_config = SettingsConfigDict(env_prefix="HPC_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if len(self.jwt_secret.encode("utf-8")) < 32:
            raise ValueError("HPC_JWT_SECRET must contain at least 32 bytes")
        if self.env.lower() == "prod" and self.jwt_secret in {"replace-with-long-random-secret", "change-me", "secret"}:
            raise ValueError("HPC_JWT_SECRET must be a unique production secret")
        if self.env.lower() == "prod" and self.bootstrap_admin_password:
            raise ValueError("bootstrap admin password must not be configured in prod")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings()
