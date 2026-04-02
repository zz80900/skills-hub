from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_title: str = "SSC Skills Library"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/skills_lib"
    admin_username: str = "admin"
    admin_password: str = "admin"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    nexus_raw_base_url: str = "http://nexus.example.invalid:8081/repository/raw-repo/skills"
    nexus_username: str = ""
    nexus_password: str = ""
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    cli_install_command: str = (
        'npm install @xgd/ssc-skills -g --registry "http://nexus.example.invalid:8081/repository/npm-all"'
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
