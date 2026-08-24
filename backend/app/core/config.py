from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_NEXGO_SKILLS_INSTALL_COMMAND = "npx nexgo-skills@latest install"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_title: str = "NEXGO Skills"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/skills_lib"
    admin_username: str = "admin"
    admin_password: str = "admin"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720
    ad_enabled: bool = False
    ad_realm: str = ""
    ad_kdc: str = ""
    ad_ldap_url: str = ""
    ad_base_dn: str = ""
    ad_domain_root_dn: str = ""
    ad_netbios_domain: str = ""
    ad_ldap_bind_username: str = ""
    ad_ldap_bind_password: str = ""
    ad_ldap_bind_principal: str = ""
    ad_kinit_command: str = "kinit"
    ad_kdestroy_command: str = "kdestroy"
    ad_kerberos_timeout_seconds: float = 15.0
    ad_ldap_timeout_seconds: float = 15.0
    rsa_private_key_pem: str | None = None
    challenge_ttl_seconds: int = 300
    rsa_max_clock_skew_seconds: int = 30
    nexus_raw_base_url: str = "http://nexus.example.invalid:8081/repository/raw-repo/skills"
    nexus_username: str = ""
    nexus_password: str = ""
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )
    mcp_enabled: bool = True
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
            "testserver",
        ]
    )
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"]
    )
    mcp_max_package_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    mcp_max_request_body_bytes: int = Field(default=32 * 1024 * 1024, gt=0)
    skills_api_base_url: str = "https://skills.sh"
    skills_api_timeout_seconds: float = 15.0
    nexgo_skills_install_command: str = DEFAULT_NEXGO_SKILLS_INSTALL_COMMAND

    @property
    def cli_install_command(self) -> str:
        return f"{self.nexgo_skills_install_command} --help"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["http://localhost:5173"]

    @field_validator("mcp_allowed_hosts", mode="before")
    @classmethod
    def parse_mcp_allowed_hosts(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "testserver"]

    @field_validator("mcp_allowed_origins", mode="before")
    @classmethod
    def parse_mcp_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["http://localhost:*", "http://127.0.0.1:*"]

    @field_validator("nexgo_skills_install_command")
    @classmethod
    def validate_nexgo_skills_install_command(cls, value: str) -> str:
        command = (value or "").strip()
        if not command:
            return DEFAULT_NEXGO_SKILLS_INSTALL_COMMAND
        if "{" in command or "}" in command:
            raise ValueError("nexgo_skills_install_command 只配置安装命令前缀，不支持占位符")
        return command


@lru_cache
def get_settings() -> Settings:
    return Settings()
