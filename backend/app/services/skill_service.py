import io
import re
import zipfile

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.skill import Skill
from app.services.markdown import render_markdown
from app.services.nexus import build_package_url


SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PUBLIC_SOURCE_LOCAL = "local"
PUBLIC_SOURCE_LOCAL_LABEL = "本地库"


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


def search_skills(session: Session, query: str | None = None) -> list[Skill]:
    statement = select(Skill).order_by(Skill.updated_at.desc(), Skill.id.desc())
    if query:
        keyword = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                Skill.name.ilike(keyword),
                Skill.description_markdown.ilike(keyword),
            )
        )
    return list(session.scalars(statement))


def get_skill_by_name(session: Session, name: str) -> Skill | None:
    statement = select(Skill).where(Skill.name == name)
    return session.scalar(statement)


def create_skill(
    session: Session,
    name: str,
    description_markdown: str,
    package_url: str,
    contributor: str | None = None,
) -> Skill:
    skill = Skill(
        name=name,
        description_markdown=description_markdown,
        description_html=render_markdown(description_markdown),
        contributor=normalize_optional_text(contributor),
        package_url=package_url,
    )
    session.add(skill)
    session.commit()
    session.refresh(skill)
    return skill


def update_skill(
    session: Session,
    skill: Skill,
    description_markdown: str | None,
    package_url: str | None,
    contributor: str | None = None,
) -> Skill:
    if description_markdown is not None:
        skill.description_markdown = description_markdown
        skill.description_html = render_markdown(description_markdown)
    if package_url is not None:
        skill.package_url = package_url
    if contributor is not None:
        skill.contributor = normalize_optional_text(contributor)
    session.add(skill)
    session.commit()
    session.refresh(skill)
    return skill


def to_skill_summary(skill: Skill) -> dict:
    return {
        "name": skill.name,
        "contributor": skill.contributor,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def to_skill_detail(skill: Skill) -> dict:
    return to_skill_summary(skill)


def to_public_skill_summary(skill: Skill) -> dict:
    return {
        "source": PUBLIC_SOURCE_LOCAL,
        "source_label": PUBLIC_SOURCE_LOCAL_LABEL,
        "slug": skill.name,
        "name": skill.name,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
        "installs": None,
    }


def to_public_skill_detail(skill: Skill) -> dict:
    return {
        **to_public_skill_summary(skill),
        "detail_url": None,
        "source_repository": None,
    }


def to_admin_skill_detail(skill: Skill) -> dict:
    return {
        "name": skill.name,
        "contributor": skill.contributor,
        "description_markdown": skill.description_markdown,
        "description_html": skill.description_html,
        "install_command": get_install_command(skill.name),
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def default_package_url(skill_name: str) -> str:
    return build_package_url(skill_name)
