from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings


def build_package_url(skill_name: str) -> str:
    settings = get_settings()
    base_url = settings.nexus_raw_base_url.rstrip("/")
    return f"{base_url}/{quote(skill_name)}.zip"


def upload_skill_zip(skill_name: str, content: bytes) -> str:
    settings = get_settings()
    if not settings.nexus_username or not settings.nexus_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Nexus 凭证未配置",
        )

    package_url = build_package_url(skill_name)
    try:
        response = httpx.put(
            package_url,
            content=content,
            auth=(settings.nexus_username, settings.nexus_password),
            headers={"Content-Type": "application/zip"},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="上传 Skill 压缩包到 Nexus 失败",
        ) from exc
    return package_url

