from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SkillSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description_html: str
    install_command: str
    created_at: datetime
    updated_at: datetime


class SkillListResponse(BaseModel):
    items: list[SkillSummary]
    cli_install_command: str


class SkillDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description_html: str
    install_command: str
    created_at: datetime
    updated_at: datetime


class AdminSkillDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description_markdown: str
    description_html: str
    install_command: str
    created_at: datetime
    updated_at: datetime
