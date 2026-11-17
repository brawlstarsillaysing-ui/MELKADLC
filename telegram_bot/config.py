from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    service_token: SecretStr
    bot_token: SecretStr
    api_base_url: str
    bot_username: str
    admin_ids: str = ""

    @field_validator("service_token")
    @classmethod
    def strong_secret(cls, value):
        if len(value.get_secret_value()) < 32:
            raise ValueError("Service token must have at least 32 characters")
        return value

    @property
    def administrators(self):
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}


@lru_cache
def settings():
    return BotSettings()
