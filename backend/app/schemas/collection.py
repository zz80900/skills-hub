from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CollectionPreviewItem(BaseModel):
    name: str
    path: str
    sha256: str
    file_count: int


class CollectionPreviewResponse(BaseModel):
    version: str
    item_count: int
    items: list[CollectionPreviewItem]


class CollectionCreateRequest(BaseModel):
    name: str
    slug: str
    description_markdown: str = ""
    scope_type: str = "PUBLIC"
    group_id: int | None = None
    scope_org_level: int | None = None
    scope_org_name: str | None = None
    scope_org_path: str | None = None


class CollectionUpdateRequest(BaseModel):
    name: str | None = None
    description_markdown: str | None = None
    scope_type: str | None = None
    group_id: int | None = None
    scope_org_level: int | None = None
    scope_org_name: str | None = None
    scope_org_path: str | None = None


class CollectionSnapshotSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: str
    item_count: int
    contributor: str | None = None
    created_at: datetime


class ManagedCollectionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    owner_username: str | None = None
    group_id: int | None = None
    group_name: str | None = None
    scope_type: str
    scope_label: str
    scope_org_level: int | None = None
    scope_org_name: str | None = None
    scope_org_path: str | None = None
    current_version: str
    item_count: int
    contributor: str | None = None
    description_html: str
    install_command: str
    is_deleted: bool = False
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ManagedCollectionDetail(ManagedCollectionSummary):
    model_config = ConfigDict(from_attributes=True)

    description_markdown: str
    manifest: dict[str, Any]
    preview_items: list[CollectionPreviewItem] = Field(default_factory=list)
    version_history: list[CollectionSnapshotSummary] = Field(default_factory=list)


class PublicCollectionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source: str
    source_label: str
    slug: str
    name: str
    description_html: str
    install_command: str
    version: str
    contributor: str | None = None
    item_count: int
    scope_type: str | None = None
    scope_label: str | None = None
    updated_at: datetime | None = None


class PublicCollectionListResponse(BaseModel):
    items: list[PublicCollectionSummary]


class PublicCollectionDetail(PublicCollectionSummary):
    manifest: dict[str, Any]
    preview_items: list[CollectionPreviewItem] = Field(default_factory=list)
    history_versions: list[str] = Field(default_factory=list)


class CollectionManifestItem(BaseModel):
    name: str
    path: str
    sha256: str
    file_count: int | None = None


class CollectionManifestResponse(BaseModel):
    schema_version: str
    slug: str
    name: str
    version: str
    package_url: str
    items: list[CollectionManifestItem]


class CollectionInstallMetadata(BaseModel):
    slug: str
    version: str
    install_command: str
    manifest_url: str
    package_url: str
