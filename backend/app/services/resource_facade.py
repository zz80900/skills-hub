from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.skill import SKILL_SCOPE_PUBLIC
from app.models.user import User
from app.schemas.auth import MessageResponse
from app.schemas.collection import (
    CollectionManifestResponse,
    CollectionPreviewResponse,
    ManagedCollectionDetail,
    ManagedCollectionSummary,
    PublicCollectionDetail,
    PublicCollectionListResponse,
    PublicCollectionSummary,
)
from app.schemas.local_library import (
    PublicLocalLibraryCollectionItem,
    PublicLocalLibrarySkillItem,
)
from app.schemas.skill import (
    ManagedSkillDetail,
    ManagedSkillSummary,
    PublicSkillDetail,
    PublicSkillSummary,
    RemoteSkillListResponse,
    SkillListResponse,
)
from app.services import nexus as nexus_service
from app.services.collection_service import (
    INITIAL_COLLECTION_VERSION,
    build_collection_package_endpoint,
    create_collection,
    get_collection_by_slug,
    get_collection_snapshot,
    get_collection_snapshots,
    get_next_collection_version,
    get_public_collection_by_slug,
    get_workspace_collection_by_slug,
    manifest_for_response,
    resolve_collection_scope,
    search_public_collections,
    search_workspace_collections,
    soft_delete_collection,
    to_collection_detail,
    to_collection_summary,
    to_public_collection_detail,
    to_public_collection_summary,
    update_collection,
    validate_collection_name,
    validate_collection_slug,
    validate_collection_version,
    validate_collection_zip_bytes,
)
from app.services.skill_service import (
    PUBLIC_SOURCE_LOCAL,
    create_skill,
    get_public_skill_by_name,
    get_skill_by_name,
    get_skill_version,
    get_skill_versions,
    get_workspace_skill_by_name,
    resolve_skill_scope,
    search_public_skills,
    search_workspace_skills,
    soft_delete_skill,
    to_admin_skill_detail,
    to_public_skill_detail as to_local_public_skill_detail,
    to_public_skill_summary as to_local_public_skill_summary,
    to_public_skill_version_detail,
    to_skill_summary,
    update_skill,
    validate_skill_name,
    validate_skill_zip_bytes,
)
from app.services.skills_registry import (
    PUBLIC_SOURCE_SKILLS_SH,
    RegistrySkillDetail,
    RegistrySkillSummary,
    get_remote_skill_detail,
    search_remote_skills,
    to_public_skill_detail as to_remote_public_skill_detail,
    to_public_skill_summary as to_remote_public_skill_summary,
)


RemoteSkillSearch = Callable[
    [str | None, int, int],
    Awaitable[tuple[list[RegistrySkillSummary], bool]],
]
RemoteSkillDetailLookup = Callable[[str], Awaitable[RegistrySkillDetail]]


@dataclass(frozen=True, slots=True)
class PackageDownloadSource:
    package_url: str
    download_path: str
    filename: str
    version: str
    requires_api_key: bool


def list_local_skill_summaries(
    session: Session,
    query: str | None,
    actor: User | None,
) -> list[PublicSkillSummary]:
    return [
        PublicSkillSummary.model_validate(to_local_public_skill_summary(skill))
        for skill in search_public_skills(session, query, actor)
    ]


def list_local_library_items(
    session: Session,
    query: str | None,
    actor: User | None,
) -> list[PublicLocalLibrarySkillItem | PublicLocalLibraryCollectionItem]:
    items: list[PublicLocalLibrarySkillItem | PublicLocalLibraryCollectionItem] = [
        PublicLocalLibrarySkillItem.model_validate(to_local_public_skill_summary(skill))
        for skill in search_public_skills(session, query, actor)
    ]
    items.extend(
        PublicLocalLibraryCollectionItem.model_validate(to_public_collection_summary(collection))
        for collection in search_public_collections(session, query, actor)
    )
    return sorted(items, key=_catalog_sort_key, reverse=True)


async def list_remote_skill_summaries(
    query: str | None,
    page: int,
    page_size: int,
    remote_search: RemoteSkillSearch | None = None,
) -> RemoteSkillListResponse:
    remote_items: list[PublicSkillSummary] = []
    remote_error: str | None = None
    remote_has_more = False
    try:
        search_operation = remote_search or search_remote_skills
        remote_results, remote_has_more = await search_operation(query, page, page_size)
        remote_items = [
            PublicSkillSummary.model_validate(to_remote_public_skill_summary(skill))
            for skill in remote_results
        ]
    except Exception:
        remote_error = "skills.sh 数据暂时不可用，请稍后重试。"

    return RemoteSkillListResponse(
        items=remote_items,
        error=remote_error,
        page=page,
        page_size=page_size,
        has_more=remote_has_more,
    )


async def search_skill_catalog(
    session: Session,
    actor: User | None,
    *,
    query: str | None,
    page: int,
    page_size: int,
    include_remote: bool,
    remote_search: RemoteSkillSearch | None = None,
) -> SkillListResponse:
    local_items = list_local_skill_summaries(session, query, actor)
    remote_response = RemoteSkillListResponse(items=[], page=page, page_size=page_size)
    if include_remote:
        session.close()
        remote_response = await list_remote_skill_summaries(query, page, page_size, remote_search)

    return SkillListResponse(
        local_items=local_items,
        remote_items=remote_response.items,
        cli_install_command=get_settings().cli_install_command,
        remote_error=remote_response.error,
        remote_page=remote_response.page,
        remote_page_size=remote_response.page_size,
        remote_has_more=remote_response.has_more,
    )


async def get_public_skill_detail(
    session: Session,
    actor: User | None,
    *,
    source: str,
    slug: str,
    version: str | None = None,
    remote_detail_lookup: RemoteSkillDetailLookup | None = None,
) -> PublicSkillDetail:
    if source == PUBLIC_SOURCE_LOCAL:
        skill = get_public_skill_by_name(session, slug, actor)
        if skill is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
        versions = get_skill_versions(session, skill)
        if version is None:
            return PublicSkillDetail.model_validate(to_local_public_skill_detail(skill, versions))
        skill_version = get_skill_version(session, skill, version)
        if skill_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 版本不存在")
        return PublicSkillDetail.model_validate(to_public_skill_version_detail(skill, skill_version, versions))

    if source == PUBLIC_SOURCE_SKILLS_SH:
        if version is not None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="skills.sh Skill 不支持版本参数")
        try:
            detail_operation = remote_detail_lookup or get_remote_skill_detail
            skill = await detail_operation(slug)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在") from exc
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="skills.sh 详情获取失败") from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="skills.sh 详情获取失败") from exc
        return PublicSkillDetail.model_validate(to_remote_public_skill_detail(skill))

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知 Skill 来源")


def list_public_collections_response(
    session: Session,
    actor: User | None,
    query: str | None,
) -> PublicCollectionListResponse:
    return PublicCollectionListResponse(
        items=[
            PublicCollectionSummary.model_validate(to_public_collection_summary(collection))
            for collection in search_public_collections(session, query, actor)
        ]
    )


def get_public_collection_detail(
    session: Session,
    actor: User | None,
    slug: str,
) -> PublicCollectionDetail:
    collection = get_public_collection_by_slug(session, validate_collection_slug(slug), actor)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    snapshots = get_collection_snapshots(session, collection)
    return PublicCollectionDetail.model_validate(to_public_collection_detail(collection, snapshots))


def get_public_collection_manifest(
    session: Session,
    actor: User | None,
    *,
    slug: str,
    version: str | None,
) -> CollectionManifestResponse:
    collection = get_public_collection_by_slug(session, validate_collection_slug(slug), actor)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")

    manifest = collection.manifest_json
    if version:
        validated_version = validate_collection_version(version)
        snapshot = get_collection_snapshot(session, collection, validated_version)
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合版本不存在")
        manifest = snapshot.manifest_json
    return CollectionManifestResponse.model_validate(manifest_for_response(collection, manifest))


def resolve_skill_download(
    session: Session,
    actor: User | None,
    slug: str,
    *,
    require_api_key_for_private: bool = False,
) -> PackageDownloadSource:
    if require_api_key_for_private and actor is None:
        private_skill = get_skill_by_name(session, slug)
        if private_skill is not None and private_skill.scope_type != SKILL_SCOPE_PUBLIC:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="该 Skill 为私有资源，请提供有效的 API Key",
            )
    skill = get_public_skill_by_name(session, slug, actor)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    return PackageDownloadSource(
        package_url=skill.package_url,
        download_path=f"/api/skills/local/{quote(skill.name, safe='')}/package",
        filename=f"{skill.name}-{skill.current_version}.zip",
        version=skill.current_version,
        requires_api_key=skill.scope_type != SKILL_SCOPE_PUBLIC,
    )


def resolve_collection_download(
    session: Session,
    actor: User | None,
    *,
    slug: str,
    version: str | None,
) -> PackageDownloadSource:
    collection = get_public_collection_by_slug(session, validate_collection_slug(slug), actor)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")

    package_url = collection.package_url
    selected_version = collection.current_version
    if version:
        validated_version = validate_collection_version(version)
        snapshot = get_collection_snapshot(session, collection, validated_version)
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合版本不存在")
        package_url = snapshot.package_url
        selected_version = validated_version
    return PackageDownloadSource(
        package_url=package_url,
        download_path=build_collection_package_endpoint(collection.slug, selected_version),
        filename=f"{collection.slug}-{selected_version}.zip",
        version=selected_version,
        requires_api_key=True,
    )


def list_managed_skills(session: Session, actor: User, query: str | None) -> list[ManagedSkillSummary]:
    return [
        ManagedSkillSummary.model_validate(to_skill_summary(skill))
        for skill in search_workspace_skills(session, actor, query)
    ]


def get_managed_skill(session: Session, actor: User, name: str) -> ManagedSkillDetail:
    skill = get_workspace_skill_by_name(session, validate_skill_name(name), actor)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, get_skill_versions(session, skill)))


def create_managed_skill(
    session: Session,
    actor: User,
    *,
    name: str,
    description_markdown: str,
    scope_type: str,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
    package_content: bytes,
    package_filename: str,
) -> ManagedSkillDetail:
    validated_name = validate_skill_name(name)
    if get_skill_by_name(session, validated_name) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在")
    zip_content = validate_skill_zip_bytes(package_content, package_filename)
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_skill_scope(
        session,
        actor,
        scope_type=scope_type,
        group_id=group_id,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )
    package_url = nexus_service.upload_skill_zip(validated_name, zip_content)
    try:
        skill = create_skill(
            session,
            actor,
            validated_name,
            description_markdown,
            package_url,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 已存在") from exc
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, get_skill_versions(session, skill)))


def update_managed_skill(
    session: Session,
    actor: User,
    *,
    name: str,
    description_markdown: str,
    scope_type: str,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
    package_content: bytes | None,
    package_filename: str | None,
) -> ManagedSkillDetail:
    validated_name = validate_skill_name(name)
    skill = get_workspace_skill_by_name(session, validated_name, actor)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_skill_scope(
        session,
        actor,
        scope_type=scope_type,
        group_id=group_id,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )
    package_url: str | None = None
    if package_content is not None:
        zip_content = validate_skill_zip_bytes(package_content, package_filename or "package.zip")
        package_url = nexus_service.upload_skill_zip(validated_name, zip_content)
    skill = update_skill(
        session,
        skill,
        description_markdown,
        package_url,
        scope_type=resolved_scope_type,
        group=group,
        scope_org_level=resolved_org_level,
        scope_org_name=resolved_org_name,
        scope_org_path=resolved_org_path,
    )
    return ManagedSkillDetail.model_validate(to_admin_skill_detail(skill, get_skill_versions(session, skill)))


def delete_managed_skill(session: Session, actor: User, name: str) -> MessageResponse:
    skill = get_workspace_skill_by_name(session, validate_skill_name(name), actor)
    if skill is None or skill.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 不存在")
    soft_delete_skill(session, skill)
    return MessageResponse(message="Skill 已删除")


def list_managed_collections(
    session: Session,
    actor: User,
    query: str | None,
) -> list[ManagedCollectionSummary]:
    return [
        ManagedCollectionSummary.model_validate(to_collection_summary(collection))
        for collection in search_workspace_collections(session, actor, query)
    ]


def preview_managed_collection(package_content: bytes, package_filename: str) -> CollectionPreviewResponse:
    _, parsed_zip = validate_collection_zip_bytes(package_content, package_filename)
    return CollectionPreviewResponse(
        version=INITIAL_COLLECTION_VERSION,
        item_count=len(parsed_zip.items),
        items=[item.__dict__ for item in parsed_zip.items],
    )


def get_managed_collection(session: Session, actor: User, slug: str) -> ManagedCollectionDetail:
    collection = get_workspace_collection_by_slug(session, validate_collection_slug(slug), actor)
    if collection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    return ManagedCollectionDetail.model_validate(
        to_collection_detail(collection, get_collection_snapshots(session, collection))
    )


def create_managed_collection(
    session: Session,
    actor: User,
    *,
    name: str,
    slug: str,
    description_markdown: str,
    scope_type: str,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
    package_content: bytes,
    package_filename: str,
) -> ManagedCollectionDetail:
    validated_slug = validate_collection_slug(slug)
    validated_name = validate_collection_name(name)
    if get_collection_by_slug(session, validated_slug) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合已存在")
    zip_content, parsed_zip = validate_collection_zip_bytes(package_content, package_filename)
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_collection_scope(
        session,
        actor,
        scope_type=scope_type,
        group_id=group_id,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )
    package_url = nexus_service.upload_collection_zip(validated_slug, INITIAL_COLLECTION_VERSION, zip_content)
    try:
        collection = create_collection(
            session,
            actor,
            name=validated_name,
            slug=validated_slug,
            description_markdown=description_markdown,
            package_url=package_url,
            parsed_zip=parsed_zip,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合已存在") from exc
    return ManagedCollectionDetail.model_validate(
        to_collection_detail(collection, get_collection_snapshots(session, collection))
    )


def update_managed_collection(
    session: Session,
    actor: User,
    *,
    slug: str,
    name: str | None,
    description_markdown: str,
    scope_type: str,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
    package_content: bytes | None,
    package_filename: str | None,
) -> ManagedCollectionDetail:
    validated_slug = validate_collection_slug(slug)
    collection = get_workspace_collection_by_slug(session, validated_slug, actor)
    if collection is None or collection.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    next_name = validate_collection_name(name or collection.name)
    resolved_scope_type, group, resolved_org_level, resolved_org_name, resolved_org_path = resolve_collection_scope(
        session,
        actor,
        scope_type=scope_type,
        group_id=group_id,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )

    package_url: str | None = None
    parsed_zip = None
    next_version: str | None = None
    if package_content is not None:
        next_version = get_next_collection_version(collection.current_version)
        zip_content, parsed_zip = validate_collection_zip_bytes(
            package_content,
            package_filename or "package.zip",
        )
        package_url = nexus_service.upload_collection_zip(validated_slug, next_version, zip_content)

    try:
        collection = update_collection(
            session,
            collection,
            name=next_name,
            description_markdown=description_markdown,
            package_url=package_url,
            parsed_zip=parsed_zip,
            version=next_version,
            scope_type=resolved_scope_type,
            group=group,
            scope_org_level=resolved_org_level,
            scope_org_name=resolved_org_name,
            scope_org_path=resolved_org_path,
        )
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill 集合版本已存在") from exc
    return ManagedCollectionDetail.model_validate(
        to_collection_detail(collection, get_collection_snapshots(session, collection))
    )


def delete_managed_collection(session: Session, actor: User, slug: str) -> MessageResponse:
    collection = get_workspace_collection_by_slug(session, validate_collection_slug(slug), actor)
    if collection is None or collection.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill 集合不存在")
    soft_delete_collection(session, collection)
    return MessageResponse(message="Skill 集合已删除")


def _catalog_sort_key(
    item: PublicLocalLibrarySkillItem | PublicLocalLibraryCollectionItem,
) -> tuple[str, str, str]:
    return (item.updated_at.isoformat() if item.updated_at else "", item.kind, item.slug)
