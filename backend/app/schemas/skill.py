from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PublicSkillSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_label: str
    slug: str
    name: str
    description_html: str
    install_command: str
    installs: int | None = None


class SkillListResponse(BaseModel):
    local_items: list[PublicSkillSummary]
    remote_items: list[PublicSkillSummary]
    cli_install_command: str
    remote_error: str | None = None
    remote_page: int = 1
    remote_page_size: int = 12
    remote_has_more: bool = False


class PublicSkillDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_label: str
    slug: str
    name: str
    description_html: str
    install_command: str
    installs: int | None = None
    detail_url: str | None = None
    source_repository: str | None = None


class AdminSkillSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    contributor: str | None = None
    description_html: str
    install_command: str
    created_at: datetime
    updated_at: datetime


class AdminSkillDetail(AdminSkillSummary):
    model_config = ConfigDict(from_attributes=True)

    description_markdown: str
