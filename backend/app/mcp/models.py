from typing import Any

from pydantic import BaseModel, Field


class McpErrorPayload(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    fields: dict[str, Any] | None = None


class McpToolEnvelope(BaseModel):
    ok: bool
    data: Any | None = None
    error: McpErrorPayload | None = None


class DownloadDescriptor(BaseModel):
    download_path: str
    filename: str
    version: str
    content_type: str = "application/zip"
    requires_api_key: bool
    resource_uri: str | None = None


class SkillCreateInput(BaseModel):
    name: str
    description_markdown: str = ""
    scope_type: str = "PUBLIC"
    group_id: int | None = Field(default=None, gt=0)
    scope_org_level: int | None = Field(default=None, gt=0)
    scope_org_name: str | None = None
    scope_org_path: str | None = None
    package_base64: str


class SkillUpdateInput(BaseModel):
    name: str
    description_markdown: str = ""
    scope_type: str = "PUBLIC"
    group_id: int | None = Field(default=None, gt=0)
    scope_org_level: int | None = Field(default=None, gt=0)
    scope_org_name: str | None = None
    scope_org_path: str | None = None
    package_base64: str | None = None


class CollectionCreateInput(BaseModel):
    name: str
    slug: str
    description_markdown: str = ""
    scope_type: str = "PUBLIC"
    group_id: int | None = Field(default=None, gt=0)
    scope_org_level: int | None = Field(default=None, gt=0)
    scope_org_name: str | None = None
    scope_org_path: str | None = None
    package_base64: str


class CollectionUpdateInput(BaseModel):
    slug: str
    name: str | None = None
    description_markdown: str = ""
    scope_type: str = "PUBLIC"
    group_id: int | None = Field(default=None, gt=0)
    scope_org_level: int | None = Field(default=None, gt=0)
    scope_org_name: str | None = None
    scope_org_path: str | None = None
    package_base64: str | None = None
