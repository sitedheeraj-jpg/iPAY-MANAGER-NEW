import json
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_id_list(value: object) -> object:
    if value is None or value == "":
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [int(item) for item in value]
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("["):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                pass
            else:
                return [int(item) for item in value]
        return [int(item.strip()) for item in raw.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    bot_token: str = Field(min_length=1)
    mongodb_uri: str = Field(min_length=1)
    mongodb_db: str = "agent_member_bot"
    owner_ids: list[int] = Field(default_factory=list)
    # Kept for backwards compatibility. When OWNER_IDS is not set, the
    # configured ADMIN_IDS become the initial owners.
    admin_ids: list[int] = Field(default_factory=list)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # OWNER_IDS and ADMIN_IDS are intentionally human-friendly CSV values
        # in hosting dashboards, not only JSON arrays.
        enable_decoding=False,
        extra="ignore",
    )

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, value: object) -> object:
        return parse_id_list(value)

    @field_validator("owner_ids", mode="before")
    @classmethod
    def parse_owner_ids(cls, value: object) -> object:
        return parse_id_list(value)

    @model_validator(mode="after")
    def use_legacy_admin_ids_as_owners(self) -> "Settings":
        if not self.owner_ids:
            self.owner_ids = list(self.admin_ids)
        return self

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()


@lru_cache
def get_settings() -> Settings:
    return Settings()