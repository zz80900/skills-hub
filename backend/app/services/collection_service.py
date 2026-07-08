import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.models.collection import COLLECTION_MANIFEST_SCHEMA_VERSION, SkillCollection, SkillCollectionSnapshot
from app.models.group import Group
from app.models.skill import SKILL_SCOPE_PUBLIC
from app.models.user import User
from app.services import visibility as visibility_service
from app.services.install_command import build_collection_install_command
from app.services.markdown import render_markdown
from app.services.user_service import ROLE_ADMIN


COLLECTION_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLLECTION_VERSION_PATTERN = re.compile(r"^(?P<major>[0-9])\.(?P<minor>[0-9])\.(?P<patch>[0-9])$")
INITIAL_COLLECTION_VERSION = "1.0.0"
MAX_COLLECTION_VERSION = "9.9.9"
PUBLIC_SOURCE_COLLECTION = "collection"
PUBLIC_SOURCE_COLLECTION_LABEL = "Skill 集合"
ZIP_COLLECTION_ROOT_FILE_DETAIL = "Skill 集合 ZIP 根目录只能包含 Skill 目录，不能包含普通文件"
ZIP_COLLECTION_EMPTY_DETAIL = "Skill 集合 ZIP 至少需要包含一个 Skill 目录"
ZIP_COLLECTION_UNSAFE_PATH_DETAIL = "Skill 集合 ZIP 包含不安全路径"
ZIP_COLLECTION_DUPLICATE_DETAIL = "Skill 集合 ZIP 包含重复的 Skill 目录名称"
ZIP_COLLECTION_SKILL_MD_DETAIL = "Skill 集合 ZIP 中的 Skill 目录缺少非空 SKILL.md"


@dataclass(frozen=True)
class CollectionZipItem:
    name: str
    path: str
    sha256: str
    file_count: int


@dataclass(frozen=True)
class ParsedCollectionZip:
    items: list[CollectionZipItem]


def validate_collection_slug(slug: str) -> str:
    normalized_slug = (slug or "").strip()
    if any(char.isspace() for char in normalized_slug):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合 slug 不能包含空格")
    if not COLLECTION_SLUG_PATTERN.fullmatch(normalized_slug):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合 slug 只允许小写字母、数字和中划线")
    return normalized_slug


def validate_collection_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合名称不能为空")
    if len(normalized_name) > 128:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合名称不能超过 128 个字符")
    return normalized_name


def validate_collection_version(version: str | None) -> str:
    normalized_version = (version or INITIAL_COLLECTION_VERSION).strip()
    if not COLLECTION_VERSION_PATTERN.fullmatch(normalized_version):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合版本必须使用 0-9.0-9.0-9 格式")
    return normalized_version


def get_next_collection_version(current_version: str) -> str:
    match = COLLECTION_VERSION_PATTERN.fullmatch((current_version or "").strip())
    if match is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Skill 集合版本数据无效")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    if (major, minor, patch) >= (9, 9, 9):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Skill 集合版本已达到 9.9.9，无法继续升级")

    if patch < 9:
        patch += 1
    else:
        patch = 0
        if minor < 9:
            minor += 1
        else:
            minor = 0
            major += 1
    return f"{major}.{minor}.{patch}"


def _raise_zip_validation_error(detail: str) -> None:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _normalize_archive_name(name: str) -> str:
    return name.replace("\\", "/")


def _is_unsafe_archive_path(name: str) -> bool:
    normalized = _normalize_archive_name(name)
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return True
    parts = normalized.rstrip("/").split("/")
    return any(part in {"", ".", ".."} for part in parts)


def _split_collection_entry(info: zipfile.ZipInfo) -> tuple[str, str | None]:
    normalized_name = _normalize_archive_name(info.filename).rstrip("/")
    if "/" not in normalized_name:
        return normalized_name, None
    root, relative_path = normalized_name.split("/", 1)
    return root, relative_path


def _read_collection_zip_items(archive: zipfile.ZipFile) -> dict[str, dict[str, zipfile.ZipInfo]]:
    skill_files: dict[str, dict[str, zipfile.ZipInfo]] = {}
    normalized_roots: dict[str, str] = {}

    for info in archive.infolist():
        if _is_unsafe_archive_path(info.filename):
            _raise_zip_validation_error(ZIP_COLLECTION_UNSAFE_PATH_DETAIL)

        root, relative_path = _split_collection_entry(info)
        normalized_root = root.casefold()
        existing_root = normalized_roots.get(normalized_root)
        if existing_root is not None and existing_root != root:
            _raise_zip_validation_error(ZIP_COLLECTION_DUPLICATE_DETAIL)
        normalized_roots[normalized_root] = root

        if relative_path is None:
            if not info.is_dir():
                _raise_zip_validation_error(ZIP_COLLECTION_ROOT_FILE_DETAIL)
            skill_files.setdefault(root, {})
            continue

        if info.is_dir():
            skill_files.setdefault(root, {})
            continue
        skill_files.setdefault(root, {})[relative_path] = info

    if not skill_files:
        _raise_zip_validation_error(ZIP_COLLECTION_EMPTY_DETAIL)
    return skill_files


def _calculate_skill_checksum(archive: zipfile.ZipFile, files: dict[str, zipfile.ZipInfo]) -> str:
    checksum = hashlib.sha256()
    for relative_path in sorted(files):
        content = archive.read(files[relative_path].filename)
        checksum.update(relative_path.encode("utf-8"))
        checksum.update(b"\0")
        checksum.update(content)
        checksum.update(b"\0")
    return checksum.hexdigest()


def parse_collection_zip(content: bytes) -> ParsedCollectionZip:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            skill_files = _read_collection_zip_items(archive)
            items: list[CollectionZipItem] = []
            for root in sorted(skill_files):
                files = skill_files[root]
                skill_md_info = files.get("SKILL.md")
                if skill_md_info is None or not archive.read(skill_md_info.filename).strip():
                    _raise_zip_validation_error(f"{ZIP_COLLECTION_SKILL_MD_DETAIL}: {root}")
                items.append(
                    CollectionZipItem(
                        name=root,
                        path=root,
                        sha256=_calculate_skill_checksum(archive, files),
                        file_count=len(files),
                    )
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="无效的 ZIP 压缩包") from exc

    return ParsedCollectionZip(items=items)


async def validate_collection_zip_file(upload_file: UploadFile) -> tuple[bytes, ParsedCollectionZip]:
    filename = upload_file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="只支持上传 ZIP 压缩包")

    content = await upload_file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="上传的 ZIP 文件不能为空")

    return content, parse_collection_zip(content)


def build_internal_manifest(
    *,
    slug: str,
    name: str,
    version: str,
    parsed_zip: ParsedCollectionZip,
) -> dict[str, Any]:
    return {
        "schema_version": COLLECTION_MANIFEST_SCHEMA_VERSION,
        "slug": slug,
        "name": name,
        "version": version,
        "items": [item.__dict__ for item in parsed_zip.items],
    }


def build_collection_package_endpoint(slug: str, version: str | None = None) -> str:
    package_url = f"/api/collections/{quote(slug, safe='')}/package"
    if version:
        package_url = f"{package_url}?version={quote(version, safe='')}"
    return package_url


def build_collection_manifest_endpoint(slug: str, version: str | None = None) -> str:
    manifest_url = f"/api/collections/{quote(slug, safe='')}/manifest"
    if version:
        manifest_url = f"{manifest_url}?version={quote(version, safe='')}"
    return manifest_url


def manifest_for_response(collection: SkillCollection, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(manifest or collection.manifest_json or {})
    version = payload.get("version") or collection.current_version
    payload["schema_version"] = payload.get("schema_version") or COLLECTION_MANIFEST_SCHEMA_VERSION
    payload["slug"] = collection.slug
    payload["name"] = collection.name
    payload["version"] = version
    payload["package_url"] = build_collection_package_endpoint(collection.slug, version)
    payload["items"] = list(payload.get("items") or [])
    return payload


def collection_preview_items(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return list(manifest.get("items") or [])


def get_collection_install_command(collection_slug: str, version: str | None = None) -> str:
    return build_collection_install_command(collection_slug, version)


def _apply_collection_query_filters(statement, query: str | None):
    if query:
        keyword = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                SkillCollection.name.ilike(keyword),
                SkillCollection.slug.ilike(keyword),
                SkillCollection.description_markdown.ilike(keyword),
            )
        )
    return statement


def _collection_resolution_order():
    return (
        case((SkillCollection.deleted_at.is_(None), 0), else_=1),
        SkillCollection.deleted_at.desc(),
        SkillCollection.id.desc(),
    )


def search_workspace_collections(session: Session, actor: User, query: str | None = None) -> list[SkillCollection]:
    statement = select(SkillCollection)
    if actor.role.name == ROLE_ADMIN:
        statement = statement.order_by(
            case((SkillCollection.deleted_at.is_(None), 0), else_=1),
            SkillCollection.deleted_at.desc(),
            SkillCollection.updated_at.desc(),
            SkillCollection.id.desc(),
        )
    else:
        statement = statement.where(
            SkillCollection.owner_id == actor.id,
            SkillCollection.deleted_at.is_(None),
        ).order_by(SkillCollection.updated_at.desc(), SkillCollection.id.desc())
    statement = _apply_collection_query_filters(statement, query)
    return list(session.scalars(statement))


def search_public_collections(session: Session, query: str | None = None, actor: User | None = None) -> list[SkillCollection]:
    statement = (
        select(SkillCollection)
        .where(SkillCollection.deleted_at.is_(None))
        .order_by(SkillCollection.updated_at.desc(), SkillCollection.id.desc())
    )
    statement = _apply_collection_query_filters(statement, query)
    statement = visibility_service.apply_public_visibility_filter(statement, SkillCollection, actor)
    return list(session.scalars(statement))


def get_collection_by_slug(session: Session, slug: str, include_deleted: bool = False) -> SkillCollection | None:
    statement = select(SkillCollection).where(SkillCollection.slug == slug)
    if not include_deleted:
        statement = statement.where(SkillCollection.deleted_at.is_(None)).order_by(SkillCollection.id.desc())
    else:
        statement = statement.order_by(*_collection_resolution_order())
    return session.scalars(statement).first()


def get_workspace_collection_by_slug(session: Session, slug: str, actor: User) -> SkillCollection | None:
    statement = select(SkillCollection).where(SkillCollection.slug == slug)
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(SkillCollection.owner_id == actor.id, SkillCollection.deleted_at.is_(None)).order_by(SkillCollection.id.desc())
    else:
        statement = statement.order_by(*_collection_resolution_order())
    return session.scalars(statement).first()


def get_public_collection_by_slug(session: Session, slug: str, actor: User | None = None) -> SkillCollection | None:
    statement = (
        select(SkillCollection)
        .where(SkillCollection.slug == slug, SkillCollection.deleted_at.is_(None))
        .order_by(SkillCollection.id.desc())
    )
    statement = visibility_service.apply_public_visibility_filter(statement, SkillCollection, actor)
    return session.scalars(statement).first()


def get_collection_snapshots(session: Session, collection: SkillCollection) -> list[SkillCollectionSnapshot]:
    statement = (
        select(SkillCollectionSnapshot)
        .where(SkillCollectionSnapshot.collection_id == collection.id)
        .order_by(SkillCollectionSnapshot.id.desc())
    )
    return list(session.scalars(statement))


def get_collection_snapshot(
    session: Session,
    collection: SkillCollection,
    version: str,
) -> SkillCollectionSnapshot | None:
    statement = (
        select(SkillCollectionSnapshot)
        .where(SkillCollectionSnapshot.collection_id == collection.id, SkillCollectionSnapshot.version == version)
        .order_by(SkillCollectionSnapshot.id.desc())
    )
    return session.scalar(statement)


def create_collection(
    session: Session,
    owner: User,
    *,
    name: str,
    slug: str,
    description_markdown: str,
    package_url: str,
    parsed_zip: ParsedCollectionZip,
    scope_type: str,
    group: Group | None = None,
    scope_org_level: int | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
) -> SkillCollection:
    contributor = (owner.display_name or owner.username).strip() or None
    description_html = render_markdown(description_markdown)
    version = INITIAL_COLLECTION_VERSION
    manifest = build_internal_manifest(slug=slug, name=name, version=version, parsed_zip=parsed_zip)
    collection = SkillCollection(
        slug=slug,
        name=name,
        owner_id=owner.id,
        description_markdown=description_markdown,
        description_html=description_html,
        contributor=contributor,
        package_url=package_url,
        current_version=version,
        manifest_json=manifest,
        item_count=len(parsed_zip.items),
        group_id=group.id if group is not None else None,
        scope_type=scope_type,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
    )
    session.add(collection)
    session.flush()
    session.add(
        SkillCollectionSnapshot(
            collection_id=collection.id,
            version=version,
            package_url=package_url,
            manifest_json=manifest,
            item_count=len(parsed_zip.items),
            description_markdown=description_markdown,
            description_html=description_html,
            contributor=contributor,
        )
    )
    session.commit()
    session.refresh(collection)
    return collection


def update_collection(
    session: Session,
    collection: SkillCollection,
    *,
    name: str,
    description_markdown: str,
    package_url: str | None,
    parsed_zip: ParsedCollectionZip | None,
    version: str | None,
    scope_type: str,
    group: Group | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
) -> SkillCollection:
    description_html = render_markdown(description_markdown)
    if parsed_zip is not None:
        next_version = version or get_next_collection_version(collection.current_version)
    else:
        next_version = collection.current_version
    next_package_url = package_url or collection.package_url
    next_manifest = (
        build_internal_manifest(slug=collection.slug, name=name, version=next_version, parsed_zip=parsed_zip)
        if parsed_zip is not None
        else {
            **dict(collection.manifest_json or {}),
            "name": name,
            "slug": collection.slug,
            "version": collection.current_version,
        }
    )
    item_count = len(parsed_zip.items) if parsed_zip is not None else collection.item_count

    collection.name = name
    collection.description_markdown = description_markdown
    collection.description_html = description_html
    collection.package_url = next_package_url
    collection.current_version = next_version
    collection.manifest_json = next_manifest
    collection.item_count = item_count
    collection.group_id = group.id if group is not None else None
    collection.scope_type = scope_type
    collection.scope_org_level = scope_org_level
    collection.scope_org_name = scope_org_name
    collection.scope_org_path = scope_org_path

    session.add(collection)
    session.flush()
    if parsed_zip is not None:
        session.add(
            SkillCollectionSnapshot(
                collection_id=collection.id,
                version=next_version,
                package_url=next_package_url,
                manifest_json=next_manifest,
                item_count=item_count,
                description_markdown=description_markdown,
                description_html=description_html,
                contributor=collection.contributor,
            )
        )
    session.commit()
    session.refresh(collection)
    return collection


def soft_delete_collection(session: Session, collection: SkillCollection) -> None:
    collection.deleted_at = datetime.now(timezone.utc)
    session.add(collection)
    session.commit()


def resolve_collection_scope(
    session: Session,
    actor: User,
    *,
    scope_type: str | None,
    group_id: int | None,
    scope_org_level: int | None,
    scope_org_name: str | None,
    scope_org_path: str | None,
) -> tuple[str, Group | None, int | None, str | None, str | None]:
    return visibility_service.resolve_visibility_scope(
        session,
        actor,
        scope_type=scope_type,
        group_id=group_id,
        scope_org_level=scope_org_level,
        scope_org_name=scope_org_name,
        scope_org_path=scope_org_path,
        entity_label="Skill 集合",
    )


def to_collection_summary(collection: SkillCollection) -> dict[str, Any]:
    return {
        "id": collection.id,
        "slug": collection.slug,
        "name": collection.name,
        "owner_username": collection.owner.username,
        "group_id": collection.group_id,
        "group_name": collection.group.name if collection.group is not None else None,
        "scope_type": collection.scope_type or SKILL_SCOPE_PUBLIC,
        "scope_label": visibility_service.build_scope_label(collection),
        "scope_org_level": collection.scope_org_level,
        "scope_org_name": collection.scope_org_name,
        "scope_org_path": collection.scope_org_path,
        "current_version": collection.current_version,
        "item_count": collection.item_count,
        "contributor": collection.contributor,
        "description_html": collection.description_html,
        "install_command": get_collection_install_command(collection.slug),
        "is_deleted": collection.deleted_at is not None,
        "deleted_at": collection.deleted_at,
        "created_at": collection.created_at,
        "updated_at": collection.updated_at,
    }


def to_collection_snapshot_summary(snapshot: SkillCollectionSnapshot) -> dict[str, Any]:
    return {
        "version": snapshot.version,
        "item_count": snapshot.item_count,
        "contributor": snapshot.contributor,
        "created_at": snapshot.created_at,
    }


def to_collection_detail(collection: SkillCollection, snapshots: list[SkillCollectionSnapshot]) -> dict[str, Any]:
    manifest = manifest_for_response(collection)
    return {
        **to_collection_summary(collection),
        "description_markdown": collection.description_markdown,
        "manifest": manifest,
        "preview_items": collection_preview_items(manifest),
        "version_history": [to_collection_snapshot_summary(snapshot) for snapshot in snapshots],
    }


def to_public_collection_summary(collection: SkillCollection) -> dict[str, Any]:
    return {
        "kind": "collection",
        "source": PUBLIC_SOURCE_COLLECTION,
        "source_label": PUBLIC_SOURCE_COLLECTION_LABEL,
        "slug": collection.slug,
        "name": collection.name,
        "description_html": collection.description_html,
        "install_command": get_collection_install_command(collection.slug),
        "version": collection.current_version,
        "contributor": collection.contributor,
        "item_count": collection.item_count,
        "scope_type": collection.scope_type,
        "scope_label": visibility_service.build_scope_label(collection),
        "updated_at": collection.updated_at,
    }


def to_public_collection_detail(collection: SkillCollection, snapshots: list[SkillCollectionSnapshot]) -> dict[str, Any]:
    manifest = manifest_for_response(collection)
    return {
        **to_public_collection_summary(collection),
        "manifest": manifest,
        "preview_items": collection_preview_items(manifest),
        "history_versions": [snapshot.version for snapshot in snapshots],
    }


def to_collection_install_metadata(collection: SkillCollection) -> dict[str, Any]:
    return {
        "slug": collection.slug,
        "version": collection.current_version,
        "install_command": get_collection_install_command(collection.slug),
        "manifest_url": build_collection_manifest_endpoint(collection.slug),
        "package_url": build_collection_package_endpoint(collection.slug),
    }
