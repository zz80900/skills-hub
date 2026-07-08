from app.core.config import get_settings


def build_skill_install_command(skill_ref: str) -> str:
    normalized_ref = skill_ref.strip().strip("/")
    skill_name = normalized_ref.rsplit("/", 1)[-1]
    return get_settings().skill_install_command_template.format(
        skill_ref=normalized_ref,
        skill_name=skill_name,
    )


def build_collection_install_command(collection_slug: str, version: str | None = None) -> str:
    normalized_slug = collection_slug.strip().strip("/")
    normalized_version = (version or "").strip()
    return get_settings().collection_install_command_template.format(
        collection_ref=normalized_slug,
        collection_slug=normalized_slug,
        version=normalized_version,
    )
