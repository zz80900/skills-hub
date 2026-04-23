import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.models.skill import Skill, SkillVersion
from app.models.user import User
from app.services.markdown import render_markdown
from app.services.nexus import build_package_url
from app.services.user_service import ROLE_ADMIN


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_VERSION_PATTERN = re.compile(r"^(?P<major>[0-9])\.(?P<minor>[0-9])\.(?P<patch>[0-9])$")
INITIAL_SKILL_VERSION = "1.0.0"
MAX_SKILL_VERSION = "9.9.9"
PUBLIC_SOURCE_LOCAL = "local"
PUBLIC_SOURCE_LOCAL_LABEL = "本地库"
UNSET = object()
ZIP_ROOT_SKILL_MD = "SKILL.md"
ZIP_ROOT_CMD = "cmd"
ZIP_ROOT_SKILL_MD_REQUIRED_DETAIL = "ZIP 压缩包根目录必须包含 SKILL.md"
ZIP_SKILL_MD_BLANK_DETAIL = "SKILL.md 不能为空白文件"
ZIP_CMD_PREFIX_DETAIL = "cmd 文件只能包含一条以 npm install 开头的命令"
ZIP_CMD_CHAIN_DETAIL = "cmd 文件不能包含其他命令或命令拼接"
ZIP_CMD_PATTERN = re.compile(r"^npm install(?:\s+.+)?$")
SKILL_NAME_SPACE_DETAIL = "Skill 名称不能包含空格"
SKILL_NAME_PATTERN_DETAIL = "Skill 名称只允许小写字母、数字和中划线"


def normalize_optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def validate_skill_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if any(char.isspace() for char in normalized_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=SKILL_NAME_SPACE_DETAIL,
        )
    if not SKILL_NAME_PATTERN.fullmatch(normalized_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=SKILL_NAME_PATTERN_DETAIL,
        )
    return normalized_name


def _raise_zip_validation_error(detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _normalize_archive_name(name: str) -> str:
    return name.replace("\\", "/").rstrip("/")


def _get_root_archive_files(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    root_files: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        normalized_name = _normalize_archive_name(info.filename)
        if info.is_dir() or not normalized_name or "/" in normalized_name:
            continue
        root_files[normalized_name] = info
    return root_files


def _read_archive_text(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    return archive.read(info.filename).decode("utf-8", errors="ignore")


def _validate_skill_md_entry(archive: zipfile.ZipFile, root_files: dict[str, zipfile.ZipInfo]) -> None:
    skill_md_info = root_files.get(ZIP_ROOT_SKILL_MD)
    if skill_md_info is None:
        _raise_zip_validation_error(ZIP_ROOT_SKILL_MD_REQUIRED_DETAIL)

    skill_md_content = _read_archive_text(archive, skill_md_info).strip()
    if not skill_md_content:
        _raise_zip_validation_error(ZIP_SKILL_MD_BLANK_DETAIL)


def _validate_cmd_entry(archive: zipfile.ZipFile, root_files: dict[str, zipfile.ZipInfo]) -> None:
    cmd_info = root_files.get(ZIP_ROOT_CMD)
    if cmd_info is None:
        return

    cmd_content = _read_archive_text(archive, cmd_info).strip()
    if not cmd_content or len(cmd_content.splitlines()) != 1:
        _raise_zip_validation_error(ZIP_CMD_PREFIX_DETAIL)

    if any(token in cmd_content for token in ("&&", "||", ";", "|")):
        _raise_zip_validation_error(ZIP_CMD_CHAIN_DETAIL)

    if not ZIP_CMD_PATTERN.fullmatch(cmd_content):
        _raise_zip_validation_error(ZIP_CMD_PREFIX_DETAIL)


async def validate_zip_file(upload_file: UploadFile) -> bytes:
    filename = upload_file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="只支持上传 ZIP 压缩包",
        )

    content = await upload_file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="上传的 ZIP 文件不能为空",
        )

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            root_files = _get_root_archive_files(archive)
            _validate_skill_md_entry(archive, root_files)
            _validate_cmd_entry(archive, root_files)
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无效的 ZIP 压缩包",
        ) from exc

    return content


def get_install_command(skill_name: str) -> str:
    return f"nexgo-skills install {skill_name}"


def get_next_version(current_version: str) -> str:
    match = SKILL_VERSION_PATTERN.fullmatch((current_version or "").strip())
    if match is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Skill 版本数据无效")

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch"))
    if (major, minor, patch) >= (9, 9, 9):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Skill 版本已达到 9.9.9，无法继续升级",
        )

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


def _apply_skill_query_filters(statement, query: str | None):
    if query:
        keyword = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Skill.name.ilike(keyword),
                Skill.description_markdown.ilike(keyword),
            )
        )
    return statement


def search_public_skills(session: Session, query: str | None = None) -> list[Skill]:
    statement = (
        select(Skill)
        .where(Skill.deleted_at.is_(None))
        .order_by(Skill.updated_at.desc(), Skill.id.desc())
    )
    statement = _apply_skill_query_filters(statement, query)
    return list(session.scalars(statement))


def _skill_name_resolution_order():
    return (
        case((Skill.deleted_at.is_(None), 0), else_=1),
        Skill.deleted_at.desc(),
        Skill.id.desc(),
    )


def get_skill_by_name(session: Session, name: str, include_deleted: bool = False) -> Skill | None:
    statement = select(Skill).where(Skill.name == name)
    if not include_deleted:
        statement = statement.where(Skill.deleted_at.is_(None)).order_by(Skill.id.desc())
    else:
        statement = statement.order_by(*_skill_name_resolution_order())
    return session.scalars(statement).first()


def get_skill_versions(session: Session, skill: Skill) -> list[SkillVersion]:
    statement = (
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id)
        .order_by(SkillVersion.id.desc())
    )
    return list(session.scalars(statement))


def get_skill_version(session: Session, skill: Skill, version: str) -> SkillVersion | None:
    statement = (
        select(SkillVersion)
        .where(SkillVersion.skill_id == skill.id, SkillVersion.version == version)
        .order_by(SkillVersion.id.desc())
    )
    return session.scalar(statement)


def search_workspace_skills(session: Session, actor: User, query: str | None = None) -> list[Skill]:
    statement = select(Skill)
    if actor.role.name == ROLE_ADMIN:
        statement = statement.order_by(
            case((Skill.deleted_at.is_(None), 0), else_=1),
            Skill.deleted_at.desc(),
            Skill.updated_at.desc(),
            Skill.id.desc(),
        )
    else:
        statement = statement.where(Skill.owner_id == actor.id, Skill.deleted_at.is_(None)).order_by(
            Skill.updated_at.desc(),
            Skill.id.desc(),
        )
    statement = _apply_skill_query_filters(statement, query)
    return list(session.scalars(statement))


def get_workspace_skill_by_name(session: Session, name: str, actor: User) -> Skill | None:
    statement = select(Skill).where(Skill.name == name)
    if actor.role.name != ROLE_ADMIN:
        statement = statement.where(Skill.owner_id == actor.id, Skill.deleted_at.is_(None)).order_by(Skill.id.desc())
    else:
        statement = statement.order_by(*_skill_name_resolution_order())
    return session.scalars(statement).first()


def create_skill(
    session: Session,
    owner: User,
    name: str,
    description_markdown: str,
    package_url: str,
) -> Skill:
    contributor = (owner.display_name or owner.username).strip() or None
    description_html = render_markdown(description_markdown)
    skill = Skill(
        name=name,
        owner_id=owner.id,
        description_markdown=description_markdown,
        description_html=description_html,
        contributor=contributor,
        package_url=package_url,
        current_version=INITIAL_SKILL_VERSION,
    )
    session.add(skill)
    session.flush()
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version=INITIAL_SKILL_VERSION,
            description_markdown=description_markdown,
            description_html=description_html,
            contributor=contributor,
            package_url=package_url,
        )
    )
    session.commit()
    session.refresh(skill)
    return skill


def update_skill(
    session: Session,
    skill: Skill,
    description_markdown: str,
    package_url: str | None,
) -> Skill:
    next_version = get_next_version(skill.current_version)
    next_package_url = package_url or skill.package_url
    description_html = render_markdown(description_markdown)

    skill.description_markdown = description_markdown
    skill.description_html = description_html
    skill.package_url = next_package_url
    skill.current_version = next_version

    session.add(skill)
    session.flush()
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version=next_version,
            description_markdown=description_markdown,
            description_html=description_html,
            contributor=skill.contributor,
            package_url=next_package_url,
        )
    )
    session.commit()
    session.refresh(skill)
    return skill


def soft_delete_skill(session: Session, skill: Skill) -> None:
    skill.deleted_at = datetime.now(timezone.utc)
    session.add(skill)
    session.commit()


def to_skill_summary(skill: Skill) -> dict[str, Any]:
    return {
        "id": skill.id,
        "name": skill.name,
        "owner_username": skill.owner.username,
        "current_version": skill.current_version,
        "contributor": skill.contributor,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
        "is_deleted": skill.deleted_at is not None,
        "deleted_at": skill.deleted_at,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def to_admin_version_summary(version: SkillVersion) -> dict[str, Any]:
    return {
        "version": version.version,
        "contributor": version.contributor,
        "created_at": version.created_at,
    }


def to_admin_skill_detail(skill: Skill, versions: list[SkillVersion]) -> dict[str, Any]:
    return {
        **to_skill_summary(skill),
        "description_markdown": skill.description_markdown,
        "version_history": [to_admin_version_summary(version) for version in versions],
    }


def to_public_skill_summary(skill: Skill) -> dict[str, Any]:
    return {
        "source": PUBLIC_SOURCE_LOCAL,
        "source_label": PUBLIC_SOURCE_LOCAL_LABEL,
        "slug": skill.name,
        "name": skill.name,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
        "installs": None,
        "version": skill.current_version,
        "contributor": skill.contributor,
    }


def _history_versions(versions: list[SkillVersion]) -> list[str]:
    return [version.version for version in versions]


def to_public_skill_detail(skill: Skill, versions: list[SkillVersion]) -> dict[str, Any]:
    return {
        **to_public_skill_summary(skill),
        "version": skill.current_version,
        "history_versions": _history_versions(versions),
        "detail_url": None,
        "source_repository": None,
    }


def to_public_skill_version_detail(
    skill: Skill,
    version: SkillVersion,
    versions: list[SkillVersion],
) -> dict[str, Any]:
    return {
        "source": PUBLIC_SOURCE_LOCAL,
        "source_label": PUBLIC_SOURCE_LOCAL_LABEL,
        "slug": skill.name,
        "name": skill.name,
        "description_html": version.description_html,
        "install_command": get_install_command(skill.name),
        "installs": None,
        "version": version.version,
        "contributor": version.contributor,
        "history_versions": _history_versions(versions),
        "detail_url": None,
        "source_repository": None,
    }


def default_package_url(skill_name: str) -> str:
    return build_package_url(skill_name)
