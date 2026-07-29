import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services import skills_registry
from app.services.markdown import render_markdown, sanitize_html


def test_render_markdown_supports_pipe_tables():
    html = render_markdown(
        """
| Request | Behavior |
| --- | --- |
| Build docs | Generate a wiki |
""".strip()
    )

    for tag in ("table", "thead", "tbody", "tr", "th", "td"):
        assert f"<{tag}" in html
    assert "<th>Request</th>" in html
    assert "<td>Generate a wiki</td>" in html


def test_render_markdown_does_not_treat_arbitrary_pipes_as_a_table():
    html = render_markdown("alpha | beta\nnot a table separator")

    assert "<table" not in html
    assert "alpha | beta" in html


def test_render_markdown_preserves_existing_commonmark_content():
    html = render_markdown("# Title\n\n- first\n- second\n\n`code`")

    assert "<h1>Title</h1>" in html
    assert "<li>first</li>" in html
    assert "<code>code</code>" in html


def test_sanitize_html_preserves_table_structure_and_removes_unsafe_attributes():
    html = sanitize_html(
        """
<table onclick="run()">
  <thead><tr><th style="text-align:right">Name</th></tr></thead>
  <tbody><tr><td onmouseover="run()">demo</td></tr></tbody>
</table>
<script>alert('unsafe')</script>
<form><input value="unsafe"></form>
""".strip()
    )

    assert "<table>" in html
    assert "<thead>" in html
    assert "<tbody>" in html
    assert "<th>Name</th>" in html
    assert "<td>demo</td>" in html
    assert "onclick" not in html
    assert "onmouseover" not in html
    assert "style=" not in html
    assert "<script" not in html
    assert "<form" not in html
    assert "<input" not in html


def test_remote_skill_detail_preserves_safe_table_and_removes_dangerous_html(monkeypatch):
    async def fake_request_text(url: str) -> str:
        assert url == "https://skills.example.com/example/repo/table-skill"
        return """
<html>
  <body>
    <article>
      <h1>table-skill</h1>
      <table onclick="run()">
        <thead><tr><th>Request</th><th>Behavior</th></tr></thead>
        <tbody><tr><td>Build docs</td><td>Generate a wiki</td></tr></tbody>
      </table>
      <script>alert('unsafe')</script>
      <form><input value="unsafe"></form>
    </article>
  </body>
</html>
"""

    monkeypatch.setattr(
        skills_registry,
        "get_settings",
        lambda: SimpleNamespace(skills_api_base_url="https://skills.example.com"),
    )
    monkeypatch.setattr(skills_registry, "_request_text", fake_request_text)

    detail = asyncio.run(skills_registry.get_remote_skill_detail("example/repo/table-skill"))

    assert "<table>" in detail.description_html
    assert "<th>Request</th>" in detail.description_html
    assert "<td>Generate a wiki</td>" in detail.description_html
    assert "onclick" not in detail.description_html
    assert "<script" not in detail.description_html
    assert "<form" not in detail.description_html
