from app.core.config import get_settings


def build_skill_install_command(skill_ref: str) -> str:
    normalized_ref = skill_ref.strip().strip("/")
    return f"{get_settings().nexgo_skills_install_command} {normalized_ref}"


def build_collection_install_command(collection_slug: str) -> str:
    normalized_slug = collection_slug.strip().strip("/")
    return f"{get_settings().nexgo_skills_install_command} collection {normalized_slug}"
