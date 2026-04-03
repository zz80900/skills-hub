import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

test_db_path = Path(__file__).with_name("test.db")
if test_db_path.exists():
    test_db_path.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-123456"
os.environ["NEXUS_USERNAME"] = "tester"
os.environ["NEXUS_PASSWORD"] = "tester"

from fastapi.testclient import TestClient

from app.api import public as public_api
from app.db.base import Base
from app.db.schema import ensure_schema_compatibility
from app.db.session import engine
from app.main import app
from app.services import nexus as nexus_service
from app.services.skills_registry import RegistrySkillDetail, RegistrySkillSummary


def make_zip(skill_md_content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", skill_md_content)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/admin/login", json={"username": "admin", "password": "admin"})
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_success(client: TestClient):
    response = client.post("/api/admin/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_app_healthcheck(client: TestClient):
    response = client.get("/api/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_upload_requires_skill_md(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", "# test")

    response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", buffer.getvalue(), "application/zip")},
        data={"name": "demo-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ZIP 压缩包中必须包含 SKILL.md"


def test_create_and_search_skill(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        return [], False

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)
    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("plm-assistant.zip", make_zip("# skill"), "application/zip")},
        data={"name": "plm-assistant", "description_markdown": "PLM 工具 Skill"},
    )
    assert response.status_code == 201

    search_response = client.get("/api/skills", params={"q": "PLM"})
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert "package_url" not in payload["local_items"][0]


def test_create_skill_stores_optional_contributor(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("plm-assistant.zip", make_zip("# skill"), "application/zip")},
        data={
            "name": "plm-assistant",
            "description_markdown": "PLM 工具 Skill",
            "contributor": "平台研发组",
        },
    )
    assert response.status_code == 201
    assert response.json()["contributor"] == "平台研发组"

    list_response = client.get("/api/admin/skills", headers=auth_headers(client))
    assert list_response.status_code == 200
    assert list_response.json()[0]["contributor"] == "平台研发组"


def test_upgrade_skill(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    create_response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo-upgrade.zip", make_zip("# first"), "application/zip")},
        data={"name": "demo-upgrade", "description_markdown": "old", "contributor": "旧贡献者"},
    )
    assert create_response.status_code == 201

    update_response = client.put(
        "/api/admin/skills/demo-upgrade",
        headers=auth_headers(client),
        files={"zip_file": ("demo-upgrade.zip", make_zip("# second"), "application/zip")},
        data={"description_markdown": "new description", "contributor": "", "contributor_submitted": "true"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description_markdown"] == "new description"
    assert update_response.json()["contributor"] is None
    assert "package_url" not in update_response.json()


def test_schema_compatibility_adds_contributor_column_for_existing_skills_table():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE skills (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(64) NOT NULL UNIQUE,
                    description_markdown TEXT NOT NULL DEFAULT '',
                    description_html TEXT NOT NULL DEFAULT '',
                    package_url VARCHAR(512) NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

    ensure_schema_compatibility(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("skills")}
    assert "contributor" in columns


def test_public_skills_groups_local_and_remote_results(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        assert page == 1
        assert page_size == 12
        return [
            RegistrySkillSummary(
                slug="vercel-labs/agent-skills/frontend-design",
                name="frontend-design",
                source="vercel-labs/agent-skills",
                installs=1234,
                description_html="<p>来源仓库：<code>vercel-labs/agent-skills</code></p>",
                install_command='ssc-skills add vercel-labs/agent-skills --as --skill "frontend-design"',
            )
        ], True

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)
    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("plm-assistant.zip", make_zip("# skill"), "application/zip")},
        data={"name": "plm-assistant", "description_markdown": "PLM 工具 Skill"},
    )
    assert create_response.status_code == 201

    response = client.get("/api/skills", params={"q": "plm"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert payload["local_items"][0]["source"] == "local"
    assert payload["remote_items"][0]["source"] == "skills_sh"
    assert payload["remote_items"][0]["install_command"].startswith("ssc-skills add vercel-labs/agent-skills --as")
    assert payload["remote_error"] is None
    assert payload["remote_has_more"] is True


def test_public_remote_detail_uses_source_and_slug(client: TestClient, monkeypatch):
    async def fake_remote_detail(slug: str):
        assert slug == "vercel-labs/agent-skills/frontend-design"
        return RegistrySkillDetail(
            slug=slug,
            name="frontend-design",
            source="vercel-labs/agent-skills",
            installs=4321,
            description_html="<p>Remote detail</p>",
            install_command='ssc-skills add vercel-labs/agent-skills --as --skill "frontend-design"',
            detail_url="https://skills.sh/vercel-labs/agent-skills/frontend-design",
        )

    monkeypatch.setattr(public_api, "get_remote_skill_detail", fake_remote_detail)

    response = client.get("/api/skills/skills_sh/vercel-labs/agent-skills/frontend-design")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "skills_sh"
    assert payload["source_repository"] == "vercel-labs/agent-skills"
    assert payload["install_command"] == 'ssc-skills add vercel-labs/agent-skills --as --skill "frontend-design"'


def test_public_remote_failure_does_not_break_local_results(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        raise RuntimeError("skills.sh unavailable")

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)
    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip("# skill"), "application/zip")},
        data={"name": "demo-skill", "description_markdown": "local detail"},
    )
    assert create_response.status_code == 201

    response = client.get("/api/skills")
    assert response.status_code == 200
    payload = response.json()
    assert payload["local_items"][0]["name"] == "demo-skill"
    assert payload["remote_items"] == []
    assert payload["remote_error"] == "skills.sh 数据暂时不可用，请稍后重试。"


def test_public_remote_pagination_uses_page_arguments(client, monkeypatch):
    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        assert query == "design"
        assert page == 2
        assert page_size == 6
        return [
            RegistrySkillSummary(
                slug="vercel-labs/agent-skills/ui-ux-pro-max",
                name="ui-ux-pro-max",
                source="vercel-labs/agent-skills",
                installs=999,
                description_html="<p>Remote summary</p>",
                install_command='ssc-skills add vercel-labs/agent-skills --as --skill "ui-ux-pro-max"',
            )
        ], False

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    response = client.get("/api/skills", params={"q": "design", "page": 2, "page_size": 6})
    assert response.status_code == 200
    payload = response.json()
    assert payload["remote_page"] == 2
    assert payload["remote_page_size"] == 6
    assert payload["remote_has_more"] is False
    assert payload["remote_items"][0]["slug"] == "vercel-labs/agent-skills/ui-ux-pro-max"
