import io
import os
import sys
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

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
from app.db.schema import _ensure_postgresql_skill_name_uniqueness_policy, ensure_schema_compatibility
from app.db.session import engine
from app.main import app
from app.services import user_service
from app.services.ad_auth import ActiveDirectoryIdentity, ActiveDirectoryUnavailableError
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


def auth_headers(client: TestClient, username: str = "admin", password: str = "admin") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_user_account(
    client: TestClient,
    admin_headers: dict[str, str],
    username: str,
    password: str,
    role: str = "USER",
    is_active: bool = True,
):
    response = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": password,
            "role": role,
            "is_active": is_active,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_local_skill(
    client: TestClient,
    monkeypatch,
    headers: dict[str, str],
    name: str = "demo-skill",
    description_markdown: str = "local detail",
):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=headers,
        files={"zip_file": (f"{name}.zip", make_zip("# skill"), "application/zip")},
        data={"name": name, "description_markdown": description_markdown},
    )
    assert response.status_code == 201
    return response


def make_ad_identity(
    username: str,
    *,
    display_name: str = "Alice Zhang",
    external_principal: str | None = None,
) -> ActiveDirectoryIdentity:
    normalized_username = username.lower()
    principal = f"{normalized_username}@XGD.COM"
    return ActiveDirectoryIdentity(
        username=normalized_username,
        principal=principal,
        display_name=display_name,
        name_source="displayName",
        external_principal=external_principal or principal,
        distinguished_name=f"CN={normalized_username},OU=Users,DC=xgd,DC=com",
        attributes={
            "displayName": [display_name],
            "sAMAccountName": [normalized_username],
            "userPrincipalName": [external_principal or principal],
        },
    )


def test_login_success(client: TestClient):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["username"] == "admin"
    assert payload["user"]["role"] == "ADMIN"
    assert payload["user"]["source"] == "LOCAL"
    assert payload["user"]["display_name"] is None


def test_app_healthcheck(client: TestClient):
    response = client.get("/api/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_admin_user_management_endpoints(client: TestClient):
    admin_headers = auth_headers(client)
    create_response = create_user_account(client, admin_headers, "viewer", "viewer-pass", role="USER")
    assert create_response["role"] == "USER"
    assert create_response["source"] == "LOCAL"
    assert create_response["is_active"] is True

    list_response = client.get("/api/admin/users", headers=admin_headers)
    assert list_response.status_code == 200
    usernames = {item["username"] for item in list_response.json()}
    assert {"admin", "viewer"}.issubset(usernames)

    update_response = client.put(
        f"/api/admin/users/{create_response['id']}",
        headers=admin_headers,
        json={"role": "ADMIN", "is_active": False},
    )
    assert update_response.status_code == 200
    assert update_response.json()["role"] == "ADMIN"
    assert update_response.json()["is_active"] is False

    disabled_login = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-pass"})
    assert disabled_login.status_code == 401

    enable_response = client.put(
        f"/api/admin/users/{create_response['id']}",
        headers=admin_headers,
        json={"is_active": True},
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["is_active"] is True

    reset_response = client.put(
        f"/api/admin/users/{create_response['id']}/password",
        headers=admin_headers,
        json={"password": "new-viewer-pass"},
    )
    assert reset_response.status_code == 200

    relogin_response = client.post("/api/auth/login", json={"username": "viewer", "password": "new-viewer-pass"})
    assert relogin_response.status_code == 200
    assert relogin_response.json()["user"]["role"] == "ADMIN"
    assert relogin_response.json()["user"]["source"] == "LOCAL"


def test_local_user_does_not_fallback_to_ad(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "local-pass")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("local auth should not call AD")

    monkeypatch.setattr(user_service, "authenticate_active_directory_user", fail_if_called)

    response = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"})
    assert response.status_code == 401
    assert response.json()["detail"] == "用户名或密码错误"


def test_ad_login_provisions_user(client: TestClient, monkeypatch):
    def fake_auth(username: str, password: str) -> ActiveDirectoryIdentity:
        assert username == "alice"
        assert password == "alice-pass"
        return make_ad_identity("alice", display_name="艾丽丝")

    monkeypatch.setattr(user_service, "authenticate_active_directory_user", fake_auth)

    response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["username"] == "alice"
    assert payload["user"]["role"] == "USER"
    assert payload["user"]["source"] == "AD"
    assert payload["user"]["display_name"] == "艾丽丝"

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    assert users_response.status_code == 200
    alice = next(item for item in users_response.json() if item["username"] == "alice")
    assert alice["source"] == "AD"
    assert alice["display_name"] == "艾丽丝"
    assert alice["external_principal"] == "alice@XGD.COM"


def test_existing_ad_user_login_syncs_profile(client: TestClient, monkeypatch):
    identities = iter(
        [
            make_ad_identity("alice", display_name="艾丽丝"),
            make_ad_identity("alice", display_name="艾丽丝-更新"),
        ]
    )

    monkeypatch.setattr(user_service, "authenticate_active_directory_user", lambda *_args, **_kwargs: next(identities))

    first_login = client.post("/api/auth/login", json={"username": "XGD\\alice", "password": "alice-pass"})
    assert first_login.status_code == 200
    assert first_login.json()["user"]["display_name"] == "艾丽丝"

    second_login = client.post("/api/auth/login", json={"username": "alice@xgd.com", "password": "alice-pass"})
    assert second_login.status_code == 200
    assert second_login.json()["user"]["source"] == "AD"
    assert second_login.json()["user"]["display_name"] == "艾丽丝-更新"

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    alice = next(item for item in users_response.json() if item["username"] == "alice")
    assert alice["display_name"] == "艾丽丝-更新"


def test_login_returns_503_when_ad_unavailable(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        user_service,
        "authenticate_active_directory_user",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ActiveDirectoryUnavailableError("missing AD configuration: AD_REALM, AD_KDC")
        ),
    )

    response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert response.status_code == 503
    assert response.json()["detail"] == "AD 认证服务暂不可用"


def test_reset_password_rejects_ad_user(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        user_service,
        "authenticate_active_directory_user",
        lambda *_args, **_kwargs: make_ad_identity("alice", display_name="艾丽丝"),
    )
    login_response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert login_response.status_code == 200

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    alice_id = next(item["id"] for item in users_response.json() if item["username"] == "alice")

    reset_response = client.put(
        f"/api/admin/users/{alice_id}/password",
        headers=admin_headers,
        json={"password": "new-pass"},
    )
    assert reset_response.status_code == 422
    assert reset_response.json()["detail"] == "AD 用户密码由域控管理，不支持本地重置"


def test_rename_ad_user_rejected(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        user_service,
        "authenticate_active_directory_user",
        lambda *_args, **_kwargs: make_ad_identity("alice", display_name="艾丽丝"),
    )
    login_response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert login_response.status_code == 200

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    alice_id = next(item["id"] for item in users_response.json() if item["username"] == "alice")

    update_response = client.put(
        f"/api/admin/users/{alice_id}",
        headers=admin_headers,
        json={"username": "alice-new"},
    )
    assert update_response.status_code == 422
    assert update_response.json()["detail"] == "AD 用户用户名由域账号映射，不支持手动修改"


def test_non_admin_cannot_manage_users(client: TestClient):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    response = client.get("/api/admin/users", headers=alice_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "仅管理员可访问该功能"


def test_upload_requires_skill_md(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", "# test")

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", buffer.getvalue(), "application/zip")},
        data={"name": "demo-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ZIP 压缩包中必须包含 SKILL.md"


def test_workspace_user_skill_isolation(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    create_user_account(client, admin_headers, "bob", "bob-pass")

    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")

    create_response = create_local_skill(client, monkeypatch, alice_headers, name="alice-skill")
    assert create_response.json()["owner_username"] == "alice"

    alice_list = client.get("/api/workspace/skills", headers=alice_headers)
    assert alice_list.status_code == 200
    assert [item["name"] for item in alice_list.json()] == ["alice-skill"]

    bob_list = client.get("/api/workspace/skills", headers=bob_headers)
    assert bob_list.status_code == 200
    assert bob_list.json() == []

    bob_detail = client.get("/api/workspace/skills/alice-skill", headers=bob_headers)
    assert bob_detail.status_code == 404

    admin_list = client.get("/api/workspace/skills", headers=admin_headers)
    assert admin_list.status_code == 200
    assert admin_list.json()[0]["owner_username"] == "alice"
    assert admin_list.json()[0]["is_deleted"] is False


def test_workspace_delete_hides_public_and_user_views_but_admin_sees_deleted_status(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    create_local_skill(client, monkeypatch, alice_headers, name="remove-me")

    delete_response = client.delete("/api/workspace/skills/remove-me", headers=alice_headers)
    assert delete_response.status_code == 200

    own_list = client.get("/api/workspace/skills", headers=alice_headers)
    assert own_list.status_code == 200
    assert own_list.json() == []

    own_detail = client.get("/api/workspace/skills/remove-me", headers=alice_headers)
    assert own_detail.status_code == 404

    public_list = client.get("/api/skills")
    assert public_list.status_code == 200
    assert public_list.json()["local_items"] == []

    admin_list = client.get("/api/workspace/skills", headers=admin_headers)
    assert admin_list.status_code == 200
    assert admin_list.json()[0]["name"] == "remove-me"
    assert admin_list.json()[0]["is_deleted"] is True
    assert admin_list.json()[0]["deleted_at"] is not None

    admin_detail = client.get("/api/workspace/skills/remove-me", headers=admin_headers)
    assert admin_detail.status_code == 200
    assert admin_detail.json()["is_deleted"] is True


def test_workspace_skill_can_be_recreated_after_delete(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    first_payload = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="repeat-skill",
        description_markdown="first generation",
    ).json()
    first_delete = client.delete("/api/workspace/skills/repeat-skill", headers=alice_headers)
    assert first_delete.status_code == 200

    second_response = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="repeat-skill",
        description_markdown="second generation",
    )
    assert second_response.status_code == 201
    second_payload = second_response.json()
    assert second_payload["id"] != first_payload["id"]
    assert second_payload["is_deleted"] is False
    assert second_payload["description_markdown"] == "second generation"

    admin_list = client.get("/api/workspace/skills", headers=admin_headers)
    assert admin_list.status_code == 200
    repeat_items = [item for item in admin_list.json() if item["name"] == "repeat-skill"]
    assert len(repeat_items) == 2
    assert repeat_items[0]["id"] == second_payload["id"]
    assert repeat_items[0]["is_deleted"] is False
    assert repeat_items[1]["id"] == first_payload["id"]
    assert repeat_items[1]["is_deleted"] is True
    assert repeat_items[1]["deleted_at"] is not None


def test_workspace_skill_keeps_multiple_deleted_histories_and_allows_recreate(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    for description in ("first deleted", "second deleted"):
        create_local_skill(
            client,
            monkeypatch,
            alice_headers,
            name="history-rebuild-skill",
            description_markdown=description,
        )
        delete_response = client.delete("/api/workspace/skills/history-rebuild-skill", headers=alice_headers)
        assert delete_response.status_code == 200

    recreate_response = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="history-rebuild-skill",
        description_markdown="third active",
    )
    assert recreate_response.status_code == 201
    recreate_payload = recreate_response.json()
    assert recreate_payload["is_deleted"] is False

    admin_list = client.get("/api/workspace/skills", headers=admin_headers)
    assert admin_list.status_code == 200
    items = [item for item in admin_list.json() if item["name"] == "history-rebuild-skill"]
    assert len(items) == 3
    assert sum(1 for item in items if item["is_deleted"]) == 2
    assert sum(1 for item in items if not item["is_deleted"]) == 1
    assert all(item["id"] for item in items)

    public_list = client.get("/api/skills")
    assert public_list.status_code == 200
    public_items = [item for item in public_list.json()["local_items"] if item["name"] == "history-rebuild-skill"]
    assert len(public_items) == 1
    assert public_items[0]["version"] == "1.0.0"

    own_list = client.get("/api/workspace/skills", headers=alice_headers)
    assert own_list.status_code == 200
    own_items = [item for item in own_list.json() if item["name"] == "history-rebuild-skill"]
    assert len(own_items) == 1
    assert own_items[0]["id"] == recreate_payload["id"]


def test_workspace_create_skill_returns_409_when_active_duplicate_exists(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_local_skill(client, monkeypatch, headers, name="duplicate-skill")

    response = client.post(
        "/api/workspace/skills",
        headers=headers,
        files={"zip_file": ("duplicate-skill.zip", make_zip("# duplicate"), "application/zip")},
        data={"name": "duplicate-skill", "description_markdown": "duplicate"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Skill 已存在"


def test_admin_workspace_skill_detail_prefers_active_then_latest_deleted(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    first_payload = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="resolver-skill",
        description_markdown="first deleted",
    ).json()
    first_delete = client.delete("/api/workspace/skills/resolver-skill", headers=alice_headers)
    assert first_delete.status_code == 200

    second_payload = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="resolver-skill",
        description_markdown="second deleted",
    ).json()
    second_delete = client.delete("/api/workspace/skills/resolver-skill", headers=alice_headers)
    assert second_delete.status_code == 200

    deleted_detail = client.get("/api/workspace/skills/resolver-skill", headers=admin_headers)
    assert deleted_detail.status_code == 200
    deleted_payload = deleted_detail.json()
    assert deleted_payload["id"] == second_payload["id"]
    assert deleted_payload["is_deleted"] is True
    assert deleted_payload["description_markdown"] == "second deleted"

    third_payload = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="resolver-skill",
        description_markdown="third active",
    ).json()

    active_detail = client.get("/api/workspace/skills/resolver-skill", headers=admin_headers)
    assert active_detail.status_code == 200
    active_payload = active_detail.json()
    assert active_payload["id"] == third_payload["id"]
    assert active_payload["is_deleted"] is False
    assert active_payload["description_markdown"] == "third active"
    assert active_payload["id"] not in {first_payload["id"], second_payload["id"]}


def test_create_and_search_skill(client: TestClient, monkeypatch):
    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        return [], False

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    response = create_local_skill(client, monkeypatch, auth_headers(client), name="plm-assistant")
    assert response.json()["current_version"] == "1.0.0"

    search_response = client.get("/api/skills", params={"q": "local"})
    assert search_response.status_code == 200
    payload = search_response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert "package_url" not in payload["local_items"][0]


def test_upgrade_skill_creates_new_version_history(client: TestClient, monkeypatch):
    create_response = create_local_skill(client, monkeypatch, auth_headers(client), name="demo-upgrade")
    assert create_response.json()["current_version"] == "1.0.0"

    update_response = client.put(
        "/api/workspace/skills/demo-upgrade",
        headers=auth_headers(client),
        files={"zip_file": ("demo-upgrade.zip", make_zip("# second"), "application/zip")},
        data={"description_markdown": "new description"},
    )
    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["description_markdown"] == "new description"
    assert payload["contributor"] == "admin"
    assert payload["current_version"] == "1.0.1"
    assert [item["version"] for item in payload["version_history"]] == ["1.0.1", "1.0.0"]


def test_public_local_detail_supports_history_query(client: TestClient, monkeypatch):
    create_local_skill(client, monkeypatch, auth_headers(client), name="history-skill")

    update_response = client.put(
        "/api/workspace/skills/history-skill",
        headers=auth_headers(client),
        data={"description_markdown": "second version"},
    )
    assert update_response.status_code == 200

    current_detail = client.get("/api/skills/local/history-skill")
    assert current_detail.status_code == 200
    current_payload = current_detail.json()
    assert current_payload["version"] == "1.0.1"
    assert current_payload["history_versions"] == ["1.0.1", "1.0.0"]

    old_detail = client.get("/api/skills/local/history-skill/versions/1.0.0")
    assert old_detail.status_code == 200
    old_payload = old_detail.json()
    assert old_payload["version"] == "1.0.0"
    assert "local detail" in old_payload["description_html"]


def test_version_ceiling_returns_422(client: TestClient, monkeypatch):
    create_local_skill(client, monkeypatch, auth_headers(client), name="ceiling-skill")

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE skills SET current_version = '9.9.9' WHERE name = 'ceiling-skill'")
        )

    response = client.put(
        "/api/workspace/skills/ceiling-skill",
        headers=auth_headers(client),
        data={"description_markdown": "blocked"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Skill 版本已达到 9.9.9，无法继续升级"


def test_schema_compatibility_adds_access_control_and_backfills_owner():
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
        connection.execute(
            text(
                """
                INSERT INTO skills (
                    id,
                    name,
                    description_markdown,
                    description_html,
                    package_url
                ) VALUES (
                    1,
                    'legacy-skill',
                    'legacy markdown',
                    '<p>legacy markdown</p>',
                    'http://example.invalid/legacy-skill.zip'
                )
                """
            )
        )

    ensure_schema_compatibility(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("skills")}
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    table_names = set(inspect(engine).get_table_names())
    assert {"contributor", "current_version", "deleted_at", "owner_id"}.issubset(columns)
    assert {"source", "display_name", "external_principal"}.issubset(user_columns)
    assert {"skill_versions", "roles", "users"}.issubset(table_names)

    with engine.begin() as connection:
        skill_row = connection.execute(
            text("SELECT current_version, owner_id FROM skills WHERE name = 'legacy-skill'")
        ).mappings().one()
        version_row = connection.execute(
            text("SELECT version FROM skill_versions WHERE skill_id = 1")
        ).mappings().one()
        admin_row = connection.execute(
            text("SELECT id, username, source FROM users WHERE username = 'admin'")
        ).mappings().one()
        role_rows = connection.execute(text("SELECT name FROM roles ORDER BY name")).mappings().all()

    assert skill_row["current_version"] == "1.0.0"
    assert skill_row["owner_id"] == admin_row["id"]
    assert admin_row["source"] == "LOCAL"
    assert version_row["version"] == "1.0.0"
    assert [row["name"] for row in role_rows] == ["ADMIN", "USER"]

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE skills
                SET deleted_at = CURRENT_TIMESTAMP
                WHERE id = 1
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO skills (
                    id,
                    name,
                    owner_id,
                    description_markdown,
                    description_html,
                    contributor,
                    package_url,
                    current_version,
                    deleted_at
                ) VALUES (
                    2,
                    'legacy-skill',
                    :owner_id,
                    'deleted history',
                    '<p>deleted history</p>',
                    'admin',
                    'http://example.invalid/legacy-skill-history.zip',
                    '1.0.0',
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"owner_id": admin_row["id"]},
        )
        connection.execute(
            text(
                """
                INSERT INTO skills (
                    id,
                    name,
                    owner_id,
                    description_markdown,
                    description_html,
                    contributor,
                    package_url,
                    current_version
                ) VALUES (
                    3,
                    'legacy-skill',
                    :owner_id,
                    'active legacy skill',
                    '<p>active legacy skill</p>',
                    'admin',
                    'http://example.invalid/legacy-skill-active.zip',
                    '1.0.0'
                )
                """
            ),
            {"owner_id": admin_row["id"]},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO skills (
                        id,
                        name,
                        owner_id,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        current_version
                    ) VALUES (
                        4,
                        'legacy-skill',
                        :owner_id,
                        'duplicate active legacy skill',
                        '<p>duplicate active legacy skill</p>',
                        'admin',
                        'http://example.invalid/legacy-skill-active-duplicate.zip',
                        '1.0.0'
                    )
                    """
                ),
                {"owner_id": admin_row["id"]},
            )


def test_schema_compatibility_replaces_legacy_sqlite_unique_name_index():
    legacy_db = Path(__file__).with_name("legacy-name-index.db")
    if legacy_db.exists():
        legacy_db.unlink()

    legacy_engine = create_engine(f"sqlite:///{legacy_db.as_posix()}", connect_args={"check_same_thread": False})
    try:
        with legacy_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE skills (
                        id INTEGER NOT NULL PRIMARY KEY,
                        name VARCHAR(64) NOT NULL,
                        description_markdown TEXT NOT NULL DEFAULT '',
                        description_html TEXT NOT NULL DEFAULT '',
                        package_url VARCHAR(512) NOT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(text("CREATE UNIQUE INDEX ix_skills_name ON skills (name)"))
            connection.execute(
                text(
                    """
                    INSERT INTO skills (
                        id,
                        name,
                        description_markdown,
                        description_html,
                        package_url
                    ) VALUES (
                        1,
                        'legacy-index-skill',
                        'legacy markdown',
                        '<p>legacy markdown</p>',
                        'http://example.invalid/legacy-index-skill.zip'
                    )
                    """
                )
            )

        ensure_schema_compatibility(legacy_engine)

        with legacy_engine.begin() as connection:
            admin_row = connection.execute(text("SELECT id FROM users WHERE username = 'admin'")).mappings().one()
            index_rows = connection.execute(text("PRAGMA index_list('skills')")).mappings().all()
            index_map = {row["name"]: row for row in index_rows}

            assert "uq_skills_active_name" in index_map
            assert index_map["uq_skills_active_name"]["unique"] == 1
            assert index_map["uq_skills_active_name"]["partial"] == 1
            assert "ix_skills_name" in index_map
            assert index_map["ix_skills_name"]["unique"] == 0

            connection.execute(
                text(
                    """
                    UPDATE skills
                    SET deleted_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO skills (
                        id,
                        name,
                        owner_id,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        current_version,
                        deleted_at
                    ) VALUES (
                        2,
                        'legacy-index-skill',
                        :owner_id,
                        'deleted history',
                        '<p>deleted history</p>',
                        'admin',
                        'http://example.invalid/legacy-index-skill-history.zip',
                        '1.0.0',
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"owner_id": admin_row["id"]},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO skills (
                        id,
                        name,
                        owner_id,
                        description_markdown,
                        description_html,
                        contributor,
                        package_url,
                        current_version
                    ) VALUES (
                        3,
                        'legacy-index-skill',
                        :owner_id,
                        'active legacy skill',
                        '<p>active legacy skill</p>',
                        'admin',
                        'http://example.invalid/legacy-index-skill-active.zip',
                        '1.0.0'
                    )
                    """
                ),
                {"owner_id": admin_row["id"]},
            )

        with pytest.raises(IntegrityError):
            with legacy_engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO skills (
                            id,
                            name,
                            owner_id,
                            description_markdown,
                            description_html,
                            contributor,
                            package_url,
                            current_version
                        ) VALUES (
                            4,
                            'legacy-index-skill',
                            :owner_id,
                            'duplicate active legacy skill',
                            '<p>duplicate active legacy skill</p>',
                            'admin',
                            'http://example.invalid/legacy-index-skill-active-duplicate.zip',
                            '1.0.0'
                        )
                        """
                    ),
                    {"owner_id": admin_row["id"]},
                )
    finally:
        legacy_engine.dispose()
        if legacy_db.exists():
            legacy_db.unlink()


def test_schema_compatibility_replaces_legacy_postgresql_unique_name_index():
    executed_sql: list[str] = []

    class FakeScalarResult:
        def __init__(self, values):
            self._values = values

        def scalars(self):
            return iter(self._values)

    class FakeMappingResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return iter(self._rows)

    class FakeConnection:
        def execute(self, statement, params=None):
            sql = str(statement)
            executed_sql.append(sql)
            if "FROM pg_constraint con" in sql:
                return FakeScalarResult(["skills_name_key"])
            if "FROM pg_indexes" in sql:
                return FakeMappingResult(
                    [
                        {
                            "indexname": "ix_skills_name",
                            "indexdef": "CREATE UNIQUE INDEX ix_skills_name ON public.skills USING btree (name)",
                        },
                        {
                            "indexname": "uq_skills_active_name",
                            "indexdef": (
                                "CREATE UNIQUE INDEX uq_skills_active_name ON public.skills USING btree (name) "
                                "WHERE (deleted_at IS NULL)"
                            ),
                        },
                    ]
                )
            return FakeScalarResult([])

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    _ensure_postgresql_skill_name_uniqueness_policy(FakeEngine())

    assert any('ALTER TABLE skills DROP CONSTRAINT "skills_name_key"' in sql for sql in executed_sql)
    assert any('DROP INDEX IF EXISTS "ix_skills_name"' in sql for sql in executed_sql)
    assert not any('DROP INDEX IF EXISTS "uq_skills_active_name"' in sql for sql in executed_sql)
    assert any("CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_active_name" in sql for sql in executed_sql)
    assert any("CREATE INDEX IF NOT EXISTS ix_skills_name ON skills (name)" in sql for sql in executed_sql)


def test_public_skills_groups_local_and_remote_results(client: TestClient, monkeypatch):
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
                install_command='nexgo-skills add "https://github.com/vercel-labs/agent-skills" --as --skill "frontend-design"',
            )
        ], True

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_local_skill(client, monkeypatch, auth_headers(client), name="plm-assistant")

    response = client.get("/api/skills", params={"q": "local"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert payload["local_items"][0]["source"] == "local"
    assert payload["remote_items"][0]["source"] == "skills_sh"
    assert payload["remote_items"][0]["install_command"].startswith('nexgo-skills add "https://github.com/vercel-labs/agent-skills" --as')
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
            install_command='nexgo-skills add "https://github.com/vercel-labs/agent-skills" --as --skill "frontend-design"',
            detail_url="https://skills.sh/vercel-labs/agent-skills/frontend-design",
        )

    monkeypatch.setattr(public_api, "get_remote_skill_detail", fake_remote_detail)

    response = client.get("/api/skills/skills_sh/vercel-labs/agent-skills/frontend-design")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "skills_sh"
    assert payload["source_repository"] == "vercel-labs/agent-skills"
    assert payload["install_command"] == 'nexgo-skills add "https://github.com/vercel-labs/agent-skills" --as --skill "frontend-design"'
    assert payload["version"] is None
    assert payload["history_versions"] == []


def test_public_remote_failure_does_not_break_local_results(client: TestClient, monkeypatch):
    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        raise RuntimeError("skills.sh unavailable")

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_local_skill(client, monkeypatch, auth_headers(client), name="demo-skill")

    response = client.get("/api/skills")
    assert response.status_code == 200
    payload = response.json()
    assert payload["local_items"][0]["name"] == "demo-skill"
    assert payload["remote_items"] == []
    assert payload["remote_error"] == "skills.sh 数据暂时不可用，请稍后重试。"


def test_public_config_returns_cli_install_command(client: TestClient):
    response = client.get("/api/public-config")
    assert response.status_code == 200
    command = response.json()["cli_install_command"]
    assert command.startswith("npm install")
    assert "@xgd/nexgo-skills" in command


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
                install_command='nexgo-skills add "https://github.com/vercel-labs/agent-skills" --as --skill "ui-ux-pro-max"',
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
