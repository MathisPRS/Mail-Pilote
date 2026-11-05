from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"), validation_alias="DATA_DIR")
    secret_key: str = Field(default="", validation_alias="MP_SECRET_KEY")
    public_origin: str = Field(default="", validation_alias="MP_PUBLIC_ORIGIN")
    claude_bin: str = "claude"
    claude_oauth_token: str | None = Field(default=None, validation_alias="CLAUDE_CODE_OAUTH_TOKEN")
    tz: str = "Europe/Paris"


@lru_cache
def get_settings() -> Settings:
    return Settings()
