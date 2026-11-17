from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str
    service_token: SecretStr
    key_encryption_secret: SecretStr
    key_hash_secret: SecretStr
    admin_ids: str = ""
    bot_username: str = ""
    api_base_url: str = "http://backend:8000"
    bot_token: SecretStr = SecretStr("")
    payment_card: str = ""
    payment_recipient: str = ""
    release_url: str = "https://github.com/brawlstarsillaysing-ui/MELKADLC/releases/tag/V1.1.0"

    @field_validator("database_url")
    @classmethod
    def psycopg_driver(cls, value):
        if value.startswith(("postgresql://", "postgres://")):
            return "postgresql+psycopg://" + value.split("://", 1)[1]
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("A PostgreSQL psycopg URL is required")
        return value

    @field_validator("service_token", "key_hash_secret")
    @classmethod
    def strong_secret(cls, value):
        if len(value.get_secret_value()) < 32:
            raise ValueError("Use a random secret of at least 32 characters")
        return value

    @field_validator("key_encryption_secret")
    @classmethod
    def encryption_key(cls, value):
        Fernet(value.get_secret_value().encode())
        return value

    @property
    def administrators(self) -> set[int]:
        return {int(x.strip()) for x in self.admin_ids.split(",") if x.strip()}


@lru_cache
def settings() -> Settings:
    return Settings()
