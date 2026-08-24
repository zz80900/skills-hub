from collections.abc import Iterator
from dataclasses import dataclass
from posixpath import normpath
from urllib.parse import quote, unquote, urlsplit

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class NexusPackageStream:
    content: Iterator[bytes]
    content_length: str | None


def build_package_url(skill_name: str) -> str:
    settings = get_settings()
    base_url = settings.nexus_raw_base_url.rstrip("/")
    return f"{base_url}/{quote(skill_name)}.zip"


def build_collection_package_url(collection_slug: str, version: str) -> str:
    settings = get_settings()
    base_url = settings.nexus_raw_base_url.rstrip("/")
    return f"{base_url}/collections/{quote(collection_slug)}/{quote(version)}.zip"


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


def upload_collection_zip(collection_slug: str, version: str, content: bytes) -> str:
    settings = get_settings()
    if not settings.nexus_username or not settings.nexus_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Nexus 凭证未配置",
        )

    package_url = build_collection_package_url(collection_slug, version)
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
            detail="上传 Skill 集合压缩包到 Nexus 失败",
        ) from exc
    return package_url


def open_package_stream(package_url: str) -> NexusPackageStream:
    settings = get_settings()
    if not settings.nexus_username or not settings.nexus_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Nexus 凭证未配置",
        )
    _validate_package_url(package_url, settings.nexus_raw_base_url)

    client = httpx.Client(
        auth=(settings.nexus_username, settings.nexus_password),
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    )
    try:
        request = client.build_request(
            "GET",
            package_url,
            headers={"Accept": "application/zip", "Accept-Encoding": "identity"},
        )
        response = client.send(request, stream=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        client.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="从 Nexus 读取压缩包失败",
        ) from exc

    def iter_content() -> Iterator[bytes]:
        try:
            yield from response.iter_raw()
        finally:
            response.close()
            client.close()

    return NexusPackageStream(
        content=iter_content(),
        content_length=response.headers.get("Content-Length"),
    )


def _validate_package_url(package_url: str, configured_base_url: str) -> None:
    target = urlsplit(package_url)
    base = urlsplit(configured_base_url.rstrip("/"))
    target_path = _decode_url_path(target.path)
    base_path = normpath(_decode_url_path(base.path)).rstrip("/")
    normalized_target_path = normpath(target_path)
    allowed_path_prefix = f"{base_path}/"
    invalid_port = False
    try:
        target_port = target.port
        base_port = base.port
    except ValueError:
        invalid_port = True
        target_port = None
        base_port = None
    if (
        invalid_port
        or target.scheme not in {"http", "https"}
        or target.scheme.lower() != base.scheme.lower()
        or target.hostname != base.hostname
        or target_port != base_port
        or target_path != normalized_target_path
        or "\\" in target_path
        or not normalized_target_path.startswith(allowed_path_prefix)
        or target.query
        or target.fragment
        or target.username
        or target.password
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Nexus 压缩包地址不合法",
        )


def _decode_url_path(path: str) -> str:
    decoded = path
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded
