import bleach
from markdown_it import MarkdownIt


markdown_parser = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS).union(
    {"p", "pre", "code", "h1", "h2", "h3", "h4", "h5", "h6", "img", "hr"}
)
allowed_attrs = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title"],
}


def sanitize_html(content: str) -> str:
    return bleach.clean(content or "", tags=allowed_tags, attributes=allowed_attrs, strip=True)


def render_markdown(content: str) -> str:
    html = markdown_parser.render(content or "")
    return sanitize_html(html)
