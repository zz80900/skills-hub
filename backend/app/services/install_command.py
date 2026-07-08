from app.core.config import get_settings


def build_skill_install_command(skill_ref: str) -> str:
    normalized_ref = skill_ref.strip().strip("/")
    skill_name = normalized_ref.rsplit("/", 1)[-1]
    return get_settings().skill_install_command_template.format(
        skill_ref=normalized_ref,
        skill_name=skill_name,
    )
