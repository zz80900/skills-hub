import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

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

from app.db.base import Base
from app.db.session import engine
from app.main import app
from app.services import nexus as nexus_service


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

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

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
    assert payload["items"][0]["name"] == "plm-assistant"
    assert "package_url" not in payload["items"][0]


def test_upgrade_skill(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    create_response = client.post(
        "/api/admin/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo-upgrade.zip", make_zip("# first"), "application/zip")},
        data={"name": "demo-upgrade", "description_markdown": "old"},
    )
    assert create_response.status_code == 201

    update_response = client.put(
        "/api/admin/skills/demo-upgrade",
        headers=auth_headers(client),
        files={"zip_file": ("demo-upgrade.zip", make_zip("# second"), "application/zip")},
        data={"description_markdown": "new description"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description_markdown"] == "new description"
    assert "package_url" not in update_response.json()
