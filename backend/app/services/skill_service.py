import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.skill import Skill, SkillVersion
from app.services.markdown import render_markdown
from app.services.nexus import build_package_url


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_VERSION_PATTERN = re.compile(r"^(?P<major>[0-9])\.(?P<minor>[0-9])\.(?P<patch>[0-9])$")
INITIAL_SKILL_VERSION = "1.0.0"
MAX_SKILL_VERSION = "9.9.9"
PUBLIC_SOURCE_LOCAL = "local"
PUBLIC_SOURCE_LOCAL_LABEL = "本地库"
UNSET = object()


def normalize_optional_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


def validate_skill_name(name: str) -> str:
    normalized_name = (name or "").strip()
    if not SKILL_NAME_PATTERN.fullmatch(normalized_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Skill 名称只允许小写字母、数字和中划线",
        )
    return normalized_name


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
            skill_md_name = next(
                (name for name in archive.namelist() if name.rsplit("/", 1)[-1] == "SKILL.md"),
                None,
            )
            if not skill_md_name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="ZIP 压缩包中必须包含 SKILL.md",
                )

            skill_md_content = archive.read(skill_md_name).decode("utf-8", errors="ignore").strip()
            if not skill_md_content:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="SKILL.md 不能为空白文件",
                )
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="无效的 ZIP 压缩包",
        ) from exc

    return content


def get_install_command(skill_name: str) -> str:
    return f"ssc-skills install {skill_name}"


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


def search_skills(session: Session, query: str | None = None) -> list[Skill]:
    statement = select(Skill).where(Skill.deleted_at.is_(None)).order_by(Skill.updated_at.desc(), Skill.id.desc())
    if query:
        keyword = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Skill.name.ilike(keyword),
                Skill.description_markdown.ilike(keyword),
            )
        )
    return list(session.scalars(statement))


def get_skill_by_name(session: Session, name: str, include_deleted: bool = False) -> Skill | None:
    statement = select(Skill).where(Skill.name == name)
    if not include_deleted:
        statement = statement.where(Skill.deleted_at.is_(None))
    return session.scalar(statement)


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


def create_skill(
    session: Session,
    name: str,
    description_markdown: str,
    package_url: str,
    contributor: str | None = None,
) -> Skill:
    normalized_contributor = normalize_optional_text(contributor)
    description_html = render_markdown(description_markdown)
    skill = Skill(
        name=name,
        description_markdown=description_markdown,
        description_html=description_html,
        contributor=normalized_contributor,
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
            contributor=normalized_contributor,
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
    contributor: str | object = UNSET,
) -> Skill:
    next_version = get_next_version(skill.current_version)
    next_contributor = skill.contributor if contributor is UNSET else normalize_optional_text(contributor)
    next_package_url = package_url or skill.package_url
    description_html = render_markdown(description_markdown)

    skill.description_markdown = description_markdown
    skill.description_html = description_html
    skill.contributor = next_contributor
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
            contributor=next_contributor,
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
        "name": skill.name,
        "current_version": skill.current_version,
        "contributor": skill.contributor,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
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
        "history_versions": _history_versions(versions),
        "detail_url": None,
        "source_repository": None,
    }


def default_package_url(skill_name: str) -> str:
    return build_package_url(skill_name)
