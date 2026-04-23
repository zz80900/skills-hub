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


def make_zip(
    skill_md_content: str | None = "# skill",
    *,
    skill_md_path: str = "SKILL.md",
    extra_files: dict[str, str | bytes] | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if skill_md_content is not None:
            archive.writestr(skill_md_path, skill_md_content)
        for path, content in (extra_files or {}).items():
            archive.writestr(path, content)
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


def user_list_items(payload: dict) -> list[dict]:
    return payload["items"]


def create_group_record(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    name: str,
    leader_user_id: int,
    description: str | None = None,
):
    response = client.post(
        "/api/admin/groups",
        headers=admin_headers,
        json={
            "name": name,
            "description": description,
            "leader_user_id": leader_user_id,
        },
    )
    assert response.status_code == 201
    return response.json()


def replace_group_member_list(
    client: TestClient,
    headers: dict[str, str],
    *,
    group_id: int,
    user_ids: list[int],
):
    response = client.put(
        f"/api/workspace/groups/{group_id}/members",
        headers=headers,
        json={"user_ids": user_ids},
    )
    assert response.status_code == 200
    return response.json()


def add_group_member_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    group_id: int,
    user_id: int,
):
    response = client.post(
        f"/api/workspace/groups/{group_id}/members",
        headers=headers,
        json={"user_id": user_id},
    )
    assert response.status_code == 200
    return response.json()


def remove_group_member_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    group_id: int,
    user_id: int,
):
    response = client.delete(
        f"/api/workspace/groups/{group_id}/members/{user_id}",
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()


def create_local_skill(
    client: TestClient,
    monkeypatch,
    headers: dict[str, str],
    name: str = "demo-skill",
    description_markdown: str = "local detail",
    group_id: int | None = None,
):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=headers,
        files={"zip_file": (f"{name}.zip", make_zip("# skill"), "application/zip")},
        data={
            "name": name,
            "description_markdown": description_markdown,
            **({"group_id": str(group_id)} if group_id is not None else {}),
        },
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
    list_payload = list_response.json()
    assert list_payload["page"] == 1
    assert list_payload["page_size"] == 20
    assert list_payload["total"] >= 2
    usernames = {item["username"] for item in user_list_items(list_payload)}
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
    alice = next(item for item in user_list_items(users_response.json()) if item["username"] == "alice")
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
    alice = next(item for item in user_list_items(users_response.json()) if item["username"] == "alice")
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
    alice_id = next(item["id"] for item in user_list_items(users_response.json()) if item["username"] == "alice")

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
    alice_id = next(item["id"] for item in user_list_items(users_response.json()) if item["username"] == "alice")

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


def test_admin_user_list_supports_search_and_pagination(client: TestClient):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    create_user_account(client, admin_headers, "bob", "bob-pass")
    create_user_account(client, admin_headers, "charlie", "charlie-pass")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE users
                SET display_name = 'Alice Zhang'
                WHERE username = 'alice'
                """
            )
        )

    first_page_response = client.get("/api/admin/users", headers=admin_headers, params={"page": 1, "page_size": 2})
    assert first_page_response.status_code == 200
    first_page_payload = first_page_response.json()
    assert first_page_payload["page"] == 1
    assert first_page_payload["page_size"] == 2
    assert first_page_payload["total"] == 4
    assert first_page_payload["has_more"] is True
    assert len(user_list_items(first_page_payload)) == 2

    second_page_response = client.get("/api/admin/users", headers=admin_headers, params={"page": 2, "page_size": 2})
    assert second_page_response.status_code == 200
    second_page_payload = second_page_response.json()
    assert second_page_payload["page"] == 2
    assert second_page_payload["page_size"] == 2
    assert second_page_payload["total"] == 4
    assert second_page_payload["has_more"] is False
    assert len(user_list_items(second_page_payload)) == 2

    search_by_username_response = client.get("/api/admin/users", headers=admin_headers, params={"q": "char"})
    assert search_by_username_response.status_code == 200
    search_by_username_payload = search_by_username_response.json()
    assert search_by_username_payload["total"] == 1
    assert [item["username"] for item in user_list_items(search_by_username_payload)] == ["charlie"]

    search_by_display_name_response = client.get("/api/admin/users", headers=admin_headers, params={"q": "zhang"})
    assert search_by_display_name_response.status_code == 200
    search_by_display_name_payload = search_by_display_name_response.json()
    assert search_by_display_name_payload["total"] == 1
    assert [item["username"] for item in user_list_items(search_by_display_name_payload)] == ["alice"]


def test_admin_group_management_and_leader_membership(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")

    group = create_group_record(
        client,
        admin_headers,
        name="PLM 组",
        description="负责 PLM 相关 Skill",
        leader_user_id=alice["id"],
    )
    assert group["leader_username"] == "alice"
    assert group["member_count"] == 1
    assert [member["username"] for member in group["members"]] == ["alice"]

    update_response = client.put(
        f"/api/admin/groups/{group['id']}",
        headers=admin_headers,
        json={
            "name": "平台组",
            "description": "负责平台类 Skill",
            "leader_user_id": bob["id"],
        },
    )
    assert update_response.status_code == 200
    updated_group = update_response.json()
    assert updated_group["name"] == "平台组"
    assert updated_group["leader_username"] == "bob"
    assert {member["username"] for member in updated_group["members"]} == {"alice", "bob"}

    list_response = client.get("/api/admin/groups", headers=admin_headers)
    assert list_response.status_code == 200
    assert [item["name"] for item in list_response.json()] == ["平台组"]

    bob_headers = auth_headers(client, "bob", "bob-pass")
    workspace_groups = client.get("/api/workspace/groups", headers=bob_headers)
    assert workspace_groups.status_code == 200
    assert [item["name"] for item in workspace_groups.json()] == ["平台组"]


def test_group_member_management_permissions_and_multi_group_membership(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "charlie", "charlie-pass")

    group_alpha = create_group_record(client, admin_headers, name="Alpha 组", leader_user_id=alice["id"])
    group_beta = create_group_record(client, admin_headers, name="Beta 组", leader_user_id=alice["id"])

    alice_headers = auth_headers(client, "alice", "alice-pass")
    alpha_members = replace_group_member_list(
        client,
        alice_headers,
        group_id=group_alpha["id"],
        user_ids=[alice["id"], bob["id"]],
    )
    assert {member["username"] for member in alpha_members["members"]} == {"alice", "bob"}

    beta_members = replace_group_member_list(
        client,
        alice_headers,
        group_id=group_beta["id"],
        user_ids=[alice["id"], bob["id"], charlie["id"]],
    )
    assert {member["username"] for member in beta_members["members"]} == {"alice", "bob", "charlie"}

    bob_headers = auth_headers(client, "bob", "bob-pass")
    options_response = client.get("/api/workspace/groups/options", headers=bob_headers)
    assert options_response.status_code == 200
    assert {item["name"] for item in options_response.json()} == {"Alpha 组", "Beta 组"}

    member_options_response = client.get("/api/workspace/groups/member-options", headers=alice_headers)
    assert member_options_response.status_code == 200
    assert {"admin", "alice", "bob", "charlie"}.issubset({item["username"] for item in member_options_response.json()})

    forbidden_update = client.put(
        f"/api/workspace/groups/{group_alpha['id']}/members",
        headers=bob_headers,
        json={"user_ids": [alice["id"], bob["id"], charlie["id"]]},
    )
    assert forbidden_update.status_code == 403
    assert forbidden_update.json()["detail"] == "无权维护该组成员"

    reject_remove_leader = client.put(
        f"/api/workspace/groups/{group_alpha['id']}/members",
        headers=alice_headers,
        json={"user_ids": [bob["id"]]},
    )
    assert reject_remove_leader.status_code == 422
    assert reject_remove_leader.json()["detail"] == "组长必须保留在组成员中"


def test_group_member_add_and_remove_endpoints(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    group = create_group_record(client, admin_headers, name="交互组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")

    added_group = add_group_member_record(client, alice_headers, group_id=group["id"], user_id=bob["id"])
    assert {member["username"] for member in added_group["members"]} == {"alice", "bob"}

    removed_group = remove_group_member_record(client, alice_headers, group_id=group["id"], user_id=bob["id"])
    assert [member["username"] for member in removed_group["members"]] == ["alice"]


def test_group_member_add_rejects_duplicate_and_remove_rejects_leader(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    group = create_group_record(client, admin_headers, name="重复组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")

    add_group_member_record(client, alice_headers, group_id=group["id"], user_id=bob["id"])

    duplicate_response = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "该用户已在组内"

    remove_leader_response = client.delete(
        f"/api/workspace/groups/{group['id']}/members/{alice['id']}",
        headers=alice_headers,
    )
    assert remove_leader_response.status_code == 422
    assert remove_leader_response.json()["detail"] == "组长不能被移除，请先更换组长"


def test_group_member_add_and_remove_reject_unauthorized_access(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "charlie", "charlie-pass")
    group = create_group_record(client, admin_headers, name="权限组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")

    add_group_member_record(client, alice_headers, group_id=group["id"], user_id=bob["id"])

    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    unauthorized_add = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=charlie_headers,
        json={"user_id": charlie["id"]},
    )
    assert unauthorized_add.status_code == 403
    assert unauthorized_add.json()["detail"] == "无权维护该组成员"

    unauthorized_remove = client.delete(
        f"/api/workspace/groups/{group['id']}/members/{bob['id']}",
        headers=charlie_headers,
    )
    assert unauthorized_remove.status_code == 403
    assert unauthorized_remove.json()["detail"] == "无权维护该组成员"


def test_group_member_can_view_joined_groups_and_members(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "charlie", "charlie-pass")

    alpha = create_group_record(client, admin_headers, name="Alpha 组", leader_user_id=alice["id"])
    beta = create_group_record(client, admin_headers, name="Beta 组", leader_user_id=alice["id"])

    alice_headers = auth_headers(client, "alice", "alice-pass")
    replace_group_member_list(client, alice_headers, group_id=alpha["id"], user_ids=[alice["id"], bob["id"]])
    replace_group_member_list(
        client,
        alice_headers,
        group_id=beta["id"],
        user_ids=[alice["id"], bob["id"], charlie["id"]],
    )

    bob_headers = auth_headers(client, "bob", "bob-pass")
    visible_groups = client.get("/api/workspace/groups", headers=bob_headers)
    assert visible_groups.status_code == 200

    payload = visible_groups.json()
    assert {group["name"] for group in payload} == {"Alpha 组", "Beta 组"}
    beta_group = next(group for group in payload if group["name"] == "Beta 组")
    assert {member["username"] for member in beta_group["members"]} == {"alice", "bob", "charlie"}


def test_group_member_remains_read_only_for_member_management(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "charlie", "charlie-pass")

    group = create_group_record(client, admin_headers, name="只读组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    replace_group_member_list(client, alice_headers, group_id=group["id"], user_ids=[alice["id"], bob["id"]])

    bob_headers = auth_headers(client, "bob", "bob-pass")
    member_options = client.get("/api/workspace/groups/member-options", headers=bob_headers)
    assert member_options.status_code == 403
    assert member_options.json()["detail"] == "当前用户没有可管理的组"

    add_response = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=bob_headers,
        json={"user_id": charlie["id"]},
    )
    assert add_response.status_code == 403
    assert add_response.json()["detail"] == "无权维护该组成员"

    remove_response = client.delete(
        f"/api/workspace/groups/{group['id']}/members/{alice['id']}",
        headers=bob_headers,
    )
    assert remove_response.status_code == 403
    assert remove_response.json()["detail"] == "无权维护该组成员"


def test_non_admin_cannot_define_groups(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    alice_headers = auth_headers(client, "alice", "alice-pass")

    response = client.post(
        "/api/admin/groups",
        headers=alice_headers,
        json={"name": "越权组", "leader_user_id": alice["id"]},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "仅管理员可访问该功能"


def test_admin_can_delete_group_without_skill_references(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    group = create_group_record(client, admin_headers, name="待删除组", leader_user_id=alice["id"])

    alice_headers = auth_headers(client, "alice", "alice-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
    )

    delete_response = client.delete(f"/api/admin/groups/{group['id']}", headers=admin_headers)
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "用户组已删除"

    list_response = client.get("/api/admin/groups", headers=admin_headers)
    assert list_response.status_code == 200
    assert list_response.json() == []

    with engine.begin() as connection:
        remaining_group_memberships = connection.execute(
            text("SELECT COUNT(*) AS count FROM group_memberships WHERE group_id = :group_id"),
            {"group_id": group["id"]},
        ).mappings().one()["count"]

    assert remaining_group_memberships == 0


def test_delete_group_rejects_non_admin_and_missing_group(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    group = create_group_record(client, admin_headers, name="保留组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")

    forbidden_response = client.delete(f"/api/admin/groups/{group['id']}", headers=alice_headers)
    assert forbidden_response.status_code == 403
    assert forbidden_response.json()["detail"] == "仅管理员可访问该功能"

    missing_response = client.delete("/api/admin/groups/99999", headers=admin_headers)
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "用户组不存在"


def test_delete_group_rejects_when_skill_still_references_group(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    group = create_group_record(client, admin_headers, name="技能组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")

    create_local_skill(client, monkeypatch, alice_headers, name="blocked-delete-skill", group_id=group["id"])

    delete_response = client.delete(f"/api/admin/groups/{group['id']}", headers=admin_headers)
    assert delete_response.status_code == 422
    assert delete_response.json()["detail"] == "当前组仍被 Skill 引用，不能删除"

    list_response = client.get("/api/admin/groups", headers=admin_headers)
    assert list_response.status_code == 200
    assert [item["name"] for item in list_response.json()] == ["技能组"]


def test_upload_requires_root_skill_md(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip(None, extra_files={"README.md": "# test"}), "application/zip")},
        data={"name": "demo-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ZIP 压缩包根目录必须包含 SKILL.md"


def test_upload_rejects_nested_skill_md(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip("# nested", skill_md_path="package/SKILL.md"), "application/zip")},
        data={"name": "nested-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ZIP 压缩包根目录必须包含 SKILL.md"


def test_upload_rejects_blank_root_skill_md(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip("   \n"), "application/zip")},
        data={"name": "blank-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "SKILL.md 不能为空白文件"


def test_upload_accepts_valid_root_cmd(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={
            "zip_file": (
                "demo.zip",
                make_zip("# demo", extra_files={"cmd": "npm install -g @xgd/demo-cli"}),
                "application/zip",
            )
        },
        data={"name": "cmd-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "cmd-skill"


def test_upload_rejects_cmd_without_npm_install(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip("# demo", extra_files={"cmd": "pnpm add demo"}), "application/zip")},
        data={"name": "bad-cmd-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "cmd 文件只能包含一条以 npm install 开头的命令"


def test_upload_rejects_chained_cmd(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={
            "zip_file": (
                "demo.zip",
                make_zip("# demo", extra_files={"cmd": "npm install -g @xgd/demo-cli && echo done"}),
                "application/zip",
            )
        },
        data={"name": "chain-cmd-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "cmd 文件不能包含其他命令或命令拼接"


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


def test_group_membership_does_not_grant_workspace_skill_management(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")

    group = create_group_record(client, admin_headers, name="共享组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
    )

    create_local_skill(client, monkeypatch, alice_headers, name="shared-skill", group_id=group["id"])

    bob_detail = client.get("/api/workspace/skills/shared-skill", headers=bob_headers)
    assert bob_detail.status_code == 404

    bob_delete = client.delete("/api/workspace/skills/shared-skill", headers=bob_headers)
    assert bob_delete.status_code == 404


def test_non_admin_cannot_bind_skill_to_unrelated_group_but_admin_can(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    group = create_group_record(client, admin_headers, name="Bob 组", leader_user_id=bob["id"])

    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    alice_headers = auth_headers(client, "alice", "alice-pass")
    forbidden_create = client.post(
        "/api/workspace/skills",
        headers=alice_headers,
        files={"zip_file": ("group.zip", make_zip("# group"), "application/zip")},
        data={"name": "forbidden-group-skill", "description_markdown": "# demo", "group_id": str(group["id"])},
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["detail"] == "无权将 Skill 绑定到该组"

    allowed_create = client.post(
        "/api/workspace/skills",
        headers=admin_headers,
        files={"zip_file": ("group.zip", make_zip("# group"), "application/zip")},
        data={"name": "admin-group-skill", "description_markdown": "# demo", "group_id": str(group["id"])},
    )
    assert allowed_create.status_code == 201
    assert allowed_create.json()["group_name"] == "Bob 组"


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


def test_workspace_create_skill_rejects_name_with_space(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("space-skill.zip", make_zip("# demo"), "application/zip")},
        data={"name": "space skill", "description_markdown": "invalid"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Skill 名称不能包含空格"


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


def test_upgrade_skill_rejects_name_with_space(client: TestClient, monkeypatch):
    create_local_skill(client, monkeypatch, auth_headers(client), name="space-upgrade")

    response = client.put(
        "/api/workspace/skills/space%20upgrade",
        headers=auth_headers(client),
        data={"description_markdown": "new description"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Skill 名称不能包含空格"


def test_upgrade_skill_rejects_invalid_nested_skill_md_zip(client: TestClient, monkeypatch):
    create_local_skill(client, monkeypatch, auth_headers(client), name="invalid-upgrade")

    response = client.put(
        "/api/workspace/skills/invalid-upgrade",
        headers=auth_headers(client),
        files={"zip_file": ("invalid-upgrade.zip", make_zip("# nested", skill_md_path="pkg/SKILL.md"), "application/zip")},
        data={"description_markdown": "new description"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "ZIP 压缩包根目录必须包含 SKILL.md"


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
    assert {"contributor", "current_version", "deleted_at", "group_id", "owner_id"}.issubset(columns)
    assert {"source", "display_name", "external_principal"}.issubset(user_columns)
    assert {"group_memberships", "groups", "skill_versions", "roles", "users"}.issubset(table_names)

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


def test_group_scoped_skill_visibility_filters_public_list_and_detail(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    create_user_account(client, admin_headers, "charlie", "charlie-pass")

    group = create_group_record(client, admin_headers, name="组内共享", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")
    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
    )

    create_local_skill(client, monkeypatch, alice_headers, name="team-skill", group_id=group["id"])

    anonymous_list = client.get("/api/skills")
    assert anonymous_list.status_code == 200
    assert anonymous_list.json()["local_items"] == []

    member_list = client.get("/api/skills", headers=bob_headers)
    assert member_list.status_code == 200
    assert [item["name"] for item in member_list.json()["local_items"]] == ["team-skill"]

    outsider_list = client.get("/api/skills", headers=charlie_headers)
    assert outsider_list.status_code == 200
    assert outsider_list.json()["local_items"] == []

    anonymous_detail = client.get("/api/skills/local/team-skill")
    assert anonymous_detail.status_code == 404

    member_detail = client.get("/api/skills/local/team-skill", headers=bob_headers)
    assert member_detail.status_code == 200
    assert member_detail.json()["name"] == "team-skill"

    member_version_detail = client.get("/api/skills/local/team-skill/versions/1.0.0", headers=bob_headers)
    assert member_version_detail.status_code == 200
    assert member_version_detail.json()["version"] == "1.0.0"

    outsider_detail = client.get("/api/skills/local/team-skill", headers=charlie_headers)
    assert outsider_detail.status_code == 404


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
