from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from app.core.config import get_settings
from app.services.markdown import sanitize_html


PUBLIC_SOURCE_SKILLS_SH = "skills_sh"
PUBLIC_SOURCE_SKILLS_SH_LABEL = "skills.sh"
DEFAULT_SEARCH_LIMIT = 12
SKILL_PATH_EXCLUDES = {"api", "_next", "docs", "blog", "pricing", "about", "privacy", "terms"}


@dataclass(slots=True)
class RegistrySkillSummary:
    slug: str
    name: str
    source: str
    installs: int | None
    description_html: str
    install_command: str


@dataclass(slots=True)
class RegistrySkillDetail:
    slug: str
    name: str
    source: str
    installs: int | None
    description_html: str
    install_command: str
    detail_url: str


class SkillsHomepageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return

        attributes = dict(attrs)
        href = (attributes.get("href") or "").strip()
        if not self._is_skill_href(href):
            return

        self._href = href
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            value = data.strip()
            if value:
                self._parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return

        slug = self._href.strip("/")
        name = slug.split("/")[-1]
        text = " ".join(self._parts).strip()
        self.items.append(
            {
                "slug": slug,
                "name": self._pick_skill_name(name, text),
                "source": "/".join(slug.split("/")[:-1]),
            }
        )
        self._href = None
        self._parts = []

    @staticmethod
    def _is_skill_href(href: str) -> bool:
        if not href.startswith("/") or href.startswith("//") or "?" in href or "#" in href:
            return False

        parts = [segment for segment in href.strip("/").split("/") if segment]
        if len(parts) < 3:
            return False
        if parts[0] in SKILL_PATH_EXCLUDES:
            return False
        return all("." not in segment for segment in parts[:2])

    @staticmethod
    def _pick_skill_name(fallback_name: str, text: str) -> str:
        if not text:
            return fallback_name

        tokens = [token.strip() for token in re.split(r"\s{2,}|\n", text) if token.strip()]
        for token in tokens:
            if "/" in token:
                continue
            if re.fullmatch(r"[0-9,]+", token):
                continue
            if len(token) > 120:
                continue
            return token
        return fallback_name


def build_remote_install_command(source: str, skill_name: str) -> str:
    repository_url = f'https://github.com/{source.strip().strip("/")}'
    return f'nexgo-skills add "{repository_url}" --as --skill "{skill_name}"'


def _paginate(items: list[RegistrySkillSummary], page: int, page_size: int) -> tuple[list[RegistrySkillSummary], bool]:
    start = max(page - 1, 0) * page_size
    end = start + page_size
    return items[start:end], end < len(items)


def _normalize_remote_record(slug: str, source: str, name: str, installs: int | None = None) -> RegistrySkillSummary:
    normalized_source = source.strip().strip("/")
    normalized_name = name.strip() or slug.split("/")[-1]
    return RegistrySkillSummary(
        slug=slug.strip().strip("/"),
        name=normalized_name,
        source=normalized_source,
        installs=installs,
        description_html=_build_summary_html(normalized_source, installs),
        install_command=build_remote_install_command(normalized_source, normalized_name),
    )


def _build_summary_html(source: str, installs: int | None) -> str:
    lines = [f"<p>来源仓库：<code>{escape(source)}</code></p>"]
    if installs is not None:
        lines.append(f"<p>累计安装：{installs}</p>")

    return "".join(lines)


def _extract_meta_description(html: str) -> str:
    patterns = (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def _extract_html_block(html: str, tag: str) -> str:
    match = re.search(
        rf"<{tag}\b[^>]*>(?P<content>.*?)</{tag}>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return match.group("content") if match else ""


def _extract_title(html: str, fallback_name: str) -> str:
    match = re.search(r"<h1\b[^>]*>(?P<title>.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return fallback_name

    title = re.sub(r"<[^>]+>", "", match.group("title"))
    title = re.sub(r"\s+", " ", title).strip()
    return title or fallback_name


def _absolutize_links(content: str, detail_url: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        attr_name = match.group("name")
        value = match.group("value").strip()
        if not value or value.startswith(("#", "mailto:", "http://", "https://")):
            return match.group(0)
        return f'{attr_name}="{urljoin(detail_url, value)}"'

    return re.sub(
        r'(?P<name>href|src)=["\'](?P<value>[^"\']+)["\']',
        replacer,
        content,
        flags=re.IGNORECASE,
    )


def _clean_detail_content(content: str) -> str:
    cleaned = re.sub(r"<script\b[^>]*>.*?</script>", "", content, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<style\b[^>]*>.*?</style>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<button\b[^>]*>.*?</button>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<form\b[^>]*>.*?</form>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def _build_fallback_detail_html(detail_url: str, source: str, description: str) -> str:
    content = description.strip() or "当前未能解析 skills.sh 返回的正文内容。"
    return sanitize_html(
        "".join(
            [
                f"<p>{escape(content)}</p>",
                f"<p>来源仓库：<code>{escape(source)}</code></p>",
                f'<p><a href="{escape(detail_url)}" target="_blank" rel="noreferrer">在 skills.sh 查看完整详情</a></p>',
            ]
        )
    )


async def _request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.skills_api_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


async def _request_text(url: str) -> str:
    settings = get_settings()
    timeout = httpx.Timeout(settings.skills_api_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def search_remote_skills(
    query: str | None,
    page: int = 1,
    page_size: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[list[RegistrySkillSummary], bool]:
    settings = get_settings()
    keyword = (query or "").strip()
    if not keyword:
        return await list_remote_skills(page=page, page_size=page_size)

    capped_page = max(page, 1)
    capped_page_size = max(page_size, 1)
    payload = await _request_json(
        f"{settings.skills_api_base_url.rstrip('/')}/api/search",
        params={"q": keyword, "limit": capped_page * capped_page_size},
    )
    skills = payload.get("skills") or []

    items: list[RegistrySkillSummary] = []
    for item in skills:
        slug = str(item.get("id") or "").strip().strip("/")
        source = str(item.get("source") or "").strip().strip("/")
        if not slug or not source:
            continue
        items.append(
            _normalize_remote_record(
                slug=slug,
                source=source,
                name=str(item.get("name") or "").strip(),
                installs=int(item.get("installs") or 0),
            )
        )
    return _paginate(items, capped_page, capped_page_size)


async def list_remote_skills(
    page: int = 1,
    page_size: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[list[RegistrySkillSummary], bool]:
    settings = get_settings()
    html = await _request_text(settings.skills_api_base_url.rstrip("/"))
    parser = SkillsHomepageParser()
    parser.feed(html)

    seen: set[str] = set()
    items: list[RegistrySkillSummary] = []
    for item in parser.items:
        slug = item["slug"]
        if slug in seen:
            continue
        seen.add(slug)
        items.append(
            _normalize_remote_record(
                slug=slug,
                source=item["source"],
                name=item["name"],
            )
        )
    return _paginate(items, max(page, 1), max(page_size, 1))


async def get_remote_skill_detail(slug: str) -> RegistrySkillDetail:
    settings = get_settings()
    normalized_slug = slug.strip().strip("/")
    if not normalized_slug:
        raise ValueError("Remote skill slug is required")

    detail_url = f"{settings.skills_api_base_url.rstrip('/')}/{normalized_slug}"
    html = await _request_text(detail_url)

    source = "/".join(normalized_slug.split("/")[:-1])
    fallback_name = normalized_slug.split("/")[-1]
    body_html = _extract_html_block(html, "article") or _extract_html_block(html, "main")
    body_html = _clean_detail_content(_absolutize_links(body_html, detail_url))
    description_html = sanitize_html(body_html) if body_html else ""
    if not description_html:
        description_html = _build_fallback_detail_html(detail_url, source, _extract_meta_description(html))

    name = _extract_title(body_html or html, fallback_name)

    installs_match = re.search(r"([0-9][0-9,]*)\s+Installs", html, flags=re.IGNORECASE)
    installs = int(installs_match.group(1).replace(",", "")) if installs_match else None

    return RegistrySkillDetail(
        slug=normalized_slug,
        name=name,
        source=source,
        installs=installs,
        description_html=description_html,
        install_command=build_remote_install_command(source, name),
        detail_url=detail_url,
    )


def to_public_skill_summary(skill: RegistrySkillSummary) -> dict[str, Any]:
    return {
        "source": PUBLIC_SOURCE_SKILLS_SH,
        "source_label": PUBLIC_SOURCE_SKILLS_SH_LABEL,
        "slug": skill.slug,
        "name": skill.name,
        "description_html": skill.description_html,
        "install_command": skill.install_command,
        "installs": skill.installs,
    }


def to_public_skill_detail(skill: RegistrySkillDetail) -> dict[str, Any]:
    return {
        **to_public_skill_summary(
            RegistrySkillSummary(
                slug=skill.slug,
                name=skill.name,
                source=skill.source,
                installs=skill.installs,
                description_html=skill.description_html,
                install_command=skill.install_command,
            )
        ),
        "detail_url": skill.detail_url,
        "source_repository": skill.source,
    }
