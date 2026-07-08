from functools import lru_cache
from string import Formatter
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSTALL_COMMAND_TEMPLATE_FIELDS = {"skill_ref", "skill_name"}
DEFAULT_SKILL_INSTALL_COMMAND_TEMPLATE = "npx nexgo-skills install {skill_ref}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    skills_api_base_url: str = "https://skills.sh"
    skills_api_timeout_seconds: float = 15.0
    cli_install_command: str = "npx nexgo-skills --help"
    skill_install_command_template: str = DEFAULT_SKILL_INSTALL_COMMAND_TEMPLATE

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return ["http://localhost:5173"]

    @field_validator("skill_install_command_template")
    @classmethod
    def validate_skill_install_command_template(cls, value: str) -> str:
        template = (value or "").strip()
        if not template:
            return DEFAULT_SKILL_INSTALL_COMMAND_TEMPLATE

        fields: set[str] = set()
        for _, field_name, _, _ in Formatter().parse(template):
            if field_name is None:
                continue
            root_name = field_name.split(".", 1)[0].split("[", 1)[0]
            if not root_name:
                raise ValueError("skill_install_command_template 不支持位置占位符")
            fields.add(root_name)

        unknown_fields = fields - INSTALL_COMMAND_TEMPLATE_FIELDS
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"skill_install_command_template 包含不支持的占位符：{names}")
        if not fields:
            raise ValueError("skill_install_command_template 必须包含 {skill_ref} 或 {skill_name}")

        template.format(skill_ref="demo-skill", skill_name="demo-skill")
        return template


@lru_cache
def get_settings() -> Settings:
    return Settings()
