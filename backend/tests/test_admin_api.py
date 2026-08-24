import base64
import io
import os
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, status
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

test_db_path = Path(__file__).with_name(f"test-{os.getpid()}.db")
if test_db_path.exists():
    test_db_path.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-123456"
os.environ["NEXUS_USERNAME"] = "tester"
os.environ["NEXUS_PASSWORD"] = "tester"

from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.api import public as public_api
from app.api.auth import router as auth_router
from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.schema import _ensure_postgresql_skill_name_uniqueness_policy, ensure_schema_compatibility
from app.db.session import engine, get_db
from app.main import app
from app.mcp.constants import MCP_TOOL_NAMES
from app.services import collection_service, resource_facade, skill_service, user_service
from app.services.ad_auth import ActiveDirectoryIdentity, ActiveDirectoryUnavailableError
from app.services import nexus as nexus_service
from app.services.skills_registry import RegistrySkillDetail, RegistrySkillSummary
from mcp.types import LATEST_PROTOCOL_VERSION


MCP_PROTOCOL_VERSION = "2025-11-25"


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


def make_collection_zip(entries: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
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


def create_api_key_headers(client: TestClient, jwt_headers: dict[str, str]) -> tuple[dict, dict[str, str]]:
    response = client.post("/api/auth/api-key", headers=jwt_headers)
    assert response.status_code == 201
    payload = response.json()
    return payload, {"Authorization": f"Bearer {payload['api_key']}"}


def mcp_rpc(
    client: TestClient,
    request_id: int,
    method: str,
    params: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
    path: str = "/mcp",
):
    request_headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    request_headers.update(headers or {})
    return client.post(
        path,
        headers=request_headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )


def mcp_call(
    client: TestClient,
    request_id: int,
    name: str,
    arguments: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
    path: str = "/mcp",
):
    return mcp_rpc(
        client,
        request_id,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
        headers=headers,
        path=path,
    )


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
    accept_headers_by_user_id: dict[int, dict[str, str]] | None = None,
):
    response = client.put(
        f"/api/workspace/groups/{group_id}/members",
        headers=headers,
        json={"user_ids": user_ids},
    )
    assert response.status_code == 200
    payload = response.json()
    for user_id, invitation_headers in (accept_headers_by_user_id or {}).items():
        if user_id in user_ids and user_id != payload["leader_user_id"]:
            payload = accept_group_invitation_record(
                client,
                invitation_headers,
                group_id=group_id,
            )
    return payload


def add_group_member_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    group_id: int,
    user_id: int,
    accept_headers: dict[str, str] | None = None,
):
    response = client.post(
        f"/api/workspace/groups/{group_id}/members",
        headers=headers,
        json={"user_id": user_id},
    )
    assert response.status_code == 200
    if accept_headers is not None:
        return accept_group_invitation_record(client, accept_headers, group_id=group_id)
    return response.json()


def accept_group_invitation_record(
    client: TestClient,
    headers: dict[str, str],
    *,
    group_id: int,
):
    inbox_response = client.get("/api/workspace/group-invitations", headers=headers)
    assert inbox_response.status_code == 200
    invitation = next(
        item for item in inbox_response.json()
        if item["group_id"] == group_id
    )
    response = client.post(
        f"/api/workspace/group-invitations/{invitation['membership_id']}/accept",
        headers=headers,
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
    scope_type: str | None = None,
    scope_org_level: int | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)
    effective_scope_type = scope_type
    if effective_scope_type is None and group_id is not None:
        effective_scope_type = "GROUP"

    data = {
        "name": name,
        "description_markdown": description_markdown,
    }
    if effective_scope_type is not None:
        data["scope_type"] = effective_scope_type
    if group_id is not None:
        data["group_id"] = str(group_id)
    if scope_org_level is not None:
        data["scope_org_level"] = str(scope_org_level)
    if scope_org_name is not None:
        data["scope_org_name"] = scope_org_name
    if scope_org_path is not None:
        data["scope_org_path"] = scope_org_path

    response = client.post(
        "/api/workspace/skills",
        headers=headers,
        files={"zip_file": (f"{name}.zip", make_zip("# skill"), "application/zip")},
        data=data,
    )
    assert response.status_code == 201
    return response


def create_collection_record(
    client: TestClient,
    monkeypatch,
    headers: dict[str, str],
    *,
    name: str = "Frontend Basic",
    slug: str = "frontend-basic",
    description_markdown: str = "collection detail",
    zip_entries: dict[str, str | bytes] | None = None,
    group_id: int | None = None,
    scope_type: str | None = None,
    scope_org_level: int | None = None,
    scope_org_name: str | None = None,
    scope_org_path: str | None = None,
):
    def fake_upload(collection_slug: str, collection_version: str, content: bytes) -> str:
        return nexus_service.build_collection_package_url(collection_slug, collection_version)

    monkeypatch.setattr(nexus_service, "upload_collection_zip", fake_upload)
    effective_scope_type = scope_type
    if effective_scope_type is None and group_id is not None:
        effective_scope_type = "GROUP"

    data = {
        "name": name,
        "slug": slug,
        "description_markdown": description_markdown,
    }
    if effective_scope_type is not None:
        data["scope_type"] = effective_scope_type
    if group_id is not None:
        data["group_id"] = str(group_id)
    if scope_org_level is not None:
        data["scope_org_level"] = str(scope_org_level)
    if scope_org_name is not None:
        data["scope_org_name"] = scope_org_name
    if scope_org_path is not None:
        data["scope_org_path"] = scope_org_path

    response = client.post(
        "/api/workspace/collections",
        headers=headers,
        files={
            "zip_file": (
                f"{slug}.zip",
                make_collection_zip(zip_entries or {"alpha/SKILL.md": "# alpha", "beta/SKILL.md": "# beta"}),
                "application/zip",
            )
        },
        data=data,
    )
    assert response.status_code == 201
    return response


def make_ad_identity(
    username: str,
    *,
    display_name: str = "Alice Zhang",
    external_principal: str | None = None,
    distinguished_name: str | None = None,
) -> ActiveDirectoryIdentity:
    normalized_username = username.lower()
    principal = f"{normalized_username}@XGD.COM"
    return ActiveDirectoryIdentity(
        username=normalized_username,
        principal=principal,
        display_name=display_name,
        name_source="displayName",
        external_principal=external_principal or principal,
        distinguished_name=distinguished_name or f"CN={normalized_username},OU=Users,DC=xgd,DC=com",
        attributes={
            "displayName": [display_name],
            "sAMAccountName": [normalized_username],
            "userPrincipalName": [external_principal or principal],
        },
    )


def login_ad_user(
    client: TestClient,
    monkeypatch,
    username: str,
    *,
    password: str = "ad-pass",
    display_name: str | None = None,
    distinguished_name: str,
) -> dict[str, str]:
    monkeypatch.setattr(
        user_service,
        "authenticate_active_directory_user",
        lambda *_args, **_kwargs: make_ad_identity(
            username,
            display_name=display_name or username,
            distinguished_name=distinguished_name,
        ),
    )
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


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
    distinguished_name = (
        "CN=alice,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
    )

    def fake_auth(username: str, password: str) -> ActiveDirectoryIdentity:
        assert username == "alice"
        assert password == "alice-pass"
        return make_ad_identity(
            "alice",
            display_name="艾丽丝",
            distinguished_name=distinguished_name,
        )

    monkeypatch.setattr(user_service, "authenticate_active_directory_user", fake_auth)

    response = client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["username"] == "alice"
    assert payload["user"]["role"] == "USER"
    assert payload["user"]["source"] == "AD"
    assert payload["user"]["display_name"] == "艾丽丝"
    assert payload["user"]["ad_distinguished_name"] == distinguished_name
    assert payload["user"]["org_level_1"] == "支付硬件事业群"
    assert payload["user"]["org_level_2"] == "技术中心"
    assert payload["user"]["org_level_3"] == "公共技术中心"
    assert payload["user"]["org_level_4"] == "系统方案部"
    assert payload["user"]["org_path"] == "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部"
    assert payload["user"]["org_depth"] == 4

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    assert users_response.status_code == 200
    alice = next(item for item in user_list_items(users_response.json()) if item["username"] == "alice")
    assert alice["source"] == "AD"
    assert alice["display_name"] == "艾丽丝"
    assert alice["external_principal"] == "alice@XGD.COM"
    assert alice["ad_distinguished_name"] == distinguished_name
    assert alice["org_level_1"] == "支付硬件事业群"
    assert alice["org_level_2"] == "技术中心"
    assert alice["org_level_3"] == "公共技术中心"
    assert alice["org_level_4"] == "系统方案部"
    assert alice["org_path"] == "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部"
    assert alice["org_depth"] == 4


def test_ad_login_provisions_user_with_partial_org_hierarchy(client: TestClient, monkeypatch):
    distinguished_name = "CN=bob,OU=平台研发部,OU=研发中心,OU=新国都集团,DC=xgd,DC=com"
    monkeypatch.setattr(
        user_service,
        "authenticate_active_directory_user",
        lambda *_args, **_kwargs: make_ad_identity(
            "bob",
            display_name="鲍勃",
            distinguished_name=distinguished_name,
        ),
    )

    response = client.post("/api/auth/login", json={"username": "bob", "password": "bob-pass"})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["ad_distinguished_name"] == distinguished_name
    assert user["org_level_1"] == "研发中心"
    assert user["org_level_2"] == "平台研发部"
    assert user["org_level_3"] is None
    assert user["org_level_4"] is None
    assert user["org_path"] == "研发中心 / 平台研发部"
    assert user["org_depth"] == 2


def test_existing_ad_user_login_syncs_profile(client: TestClient, monkeypatch):
    first_distinguished_name = (
        "CN=alice,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
    )
    second_distinguished_name = (
        "CN=alice,OU=AI创新组,OU=平台技术部,OU=研发中心,OU=软件事业群,OU=新国都集团,DC=xgd,DC=com"
    )
    identities = iter(
        [
            make_ad_identity(
                "alice",
                display_name="艾丽丝",
                distinguished_name=first_distinguished_name,
            ),
            make_ad_identity(
                "alice",
                display_name="艾丽丝-更新",
                distinguished_name=second_distinguished_name,
            ),
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
    assert second_login.json()["user"]["ad_distinguished_name"] == second_distinguished_name
    assert second_login.json()["user"]["org_level_1"] == "软件事业群"
    assert second_login.json()["user"]["org_level_2"] == "研发中心"
    assert second_login.json()["user"]["org_level_3"] == "平台技术部"
    assert second_login.json()["user"]["org_level_4"] == "AI创新组"
    assert second_login.json()["user"]["org_path"] == "软件事业群 / 研发中心 / 平台技术部 / AI创新组"

    admin_headers = auth_headers(client)
    users_response = client.get("/api/admin/users", headers=admin_headers)
    alice = next(item for item in user_list_items(users_response.json()) if item["username"] == "alice")
    assert alice["display_name"] == "艾丽丝-更新"
    assert alice["ad_distinguished_name"] == second_distinguished_name
    assert alice["org_level_1"] == "软件事业群"
    assert alice["org_level_2"] == "研发中心"
    assert alice["org_level_3"] == "平台技术部"
    assert alice["org_level_4"] == "AI创新组"
    assert alice["org_path"] == "软件事业群 / 研发中心 / 平台技术部 / AI创新组"


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

    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")
    add_group_member_record(
        client,
        alice_headers,
        group_id=group["id"],
        user_id=bob["id"],
        accept_headers=bob_headers,
    )

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
    bob_headers = auth_headers(client, "bob", "bob-pass")
    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    alpha_members = replace_group_member_list(
        client,
        alice_headers,
        group_id=group_alpha["id"],
        user_ids=[alice["id"], bob["id"]],
        accept_headers_by_user_id={bob["id"]: bob_headers},
    )
    assert {member["username"] for member in alpha_members["members"]} == {"alice", "bob"}

    beta_members = replace_group_member_list(
        client,
        alice_headers,
        group_id=group_beta["id"],
        user_ids=[alice["id"], bob["id"], charlie["id"]],
        accept_headers_by_user_id={
            bob["id"]: bob_headers,
            charlie["id"]: charlie_headers,
        },
    )
    assert {member["username"] for member in beta_members["members"]} == {"alice", "bob", "charlie"}

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
    bob_headers = auth_headers(client, "bob", "bob-pass")

    added_group = add_group_member_record(
        client,
        alice_headers,
        group_id=group["id"],
        user_id=bob["id"],
        accept_headers=bob_headers,
    )
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
    assert duplicate_response.json()["detail"] == "该用户已有待确认邀请"

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
    bob_headers = auth_headers(client, "bob", "bob-pass")
    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=alpha["id"],
        user_ids=[alice["id"], bob["id"]],
        accept_headers_by_user_id={bob["id"]: bob_headers},
    )
    replace_group_member_list(
        client,
        alice_headers,
        group_id=beta["id"],
        user_ids=[alice["id"], bob["id"], charlie["id"]],
        accept_headers_by_user_id={
            bob["id"]: bob_headers,
            charlie["id"]: charlie_headers,
        },
    )

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
    bob_headers = auth_headers(client, "bob", "bob-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
        accept_headers_by_user_id={bob["id"]: bob_headers},
    )
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


def test_regular_user_can_create_update_and_delete_own_group(client: TestClient):
    admin_headers = auth_headers(client)
    admin_user = client.get("/api/auth/me", headers=admin_headers).json()
    alice = create_user_account(client, admin_headers, "self-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "self-bob", "bob-pass")
    alice_headers = auth_headers(client, "self-alice", "alice-pass")
    bob_headers = auth_headers(client, "self-bob", "bob-pass")

    create_response = client.post(
        "/api/workspace/groups",
        headers=alice_headers,
        json={"name": "自主管理组", "description": "由普通用户创建"},
    )
    assert create_response.status_code == 201
    group = create_response.json()
    assert group["created_by_user_id"] == alice["id"]
    assert group["leader_user_id"] == alice["id"]
    assert group["member_count"] == 1
    assert group["members"][0]["status"] == "ACTIVE"

    forbidden_create = client.post(
        "/api/workspace/groups",
        headers=alice_headers,
        json={"name": "越权代建组", "leader_user_id": bob["id"]},
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["detail"] == "普通用户只能将自己设为组长"

    forbidden_update = client.put(
        f"/api/workspace/groups/{group['id']}",
        headers=bob_headers,
        json={"name": "无权修改"},
    )
    assert forbidden_update.status_code == 403

    update_response = client.put(
        f"/api/workspace/groups/{group['id']}",
        headers=alice_headers,
        json={"name": "自主管理组（更新）", "description": "更新后的说明"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "自主管理组（更新）"

    admin_create = client.post(
        "/api/admin/groups",
        headers=admin_headers,
        json={"name": "管理员代建组", "leader_user_id": bob["id"]},
    )
    assert admin_create.status_code == 201
    assert admin_create.json()["created_by_user_id"] == admin_user["id"]
    assert admin_create.json()["leader_user_id"] == bob["id"]

    forbidden_delete = client.delete(
        f"/api/workspace/groups/{group['id']}",
        headers=bob_headers,
    )
    assert forbidden_delete.status_code == 403

    delete_response = client.delete(
        f"/api/workspace/groups/{group['id']}",
        headers=alice_headers,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "用户组已删除"


def test_group_invitation_state_machine_and_visibility(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "invite-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "invite-bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "invite-charlie", "charlie-pass")
    inactive = create_user_account(
        client,
        admin_headers,
        "invite-inactive",
        "inactive-pass",
        is_active=False,
    )
    alice_headers = auth_headers(client, "invite-alice", "alice-pass")
    bob_headers = auth_headers(client, "invite-bob", "bob-pass")
    charlie_headers = auth_headers(client, "invite-charlie", "charlie-pass")

    group_response = client.post(
        "/api/workspace/groups",
        headers=alice_headers,
        json={"name": "邀请状态组"},
    )
    assert group_response.status_code == 201
    group = group_response.json()

    inactive_invite = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": inactive["id"]},
    )
    assert inactive_invite.status_code == 422
    assert inactive_invite.json()["detail"] == "用户已停用"

    invite_response = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    )
    assert invite_response.status_code == 200
    invited_group = invite_response.json()
    assert invited_group["member_count"] == 1
    assert invited_group["pending_invitation_count"] == 1
    assert invited_group["pending_invitations"][0]["username"] == "invite-bob"
    assert invited_group["pending_invitations"][0]["status"] == "PENDING"

    assert client.get("/api/workspace/groups", headers=bob_headers).json() == []
    assert client.get("/api/workspace/groups/options", headers=bob_headers).json() == []
    inbox = client.get("/api/workspace/group-invitations", headers=bob_headers)
    assert inbox.status_code == 200
    invitation = inbox.json()[0]
    assert invitation["group_id"] == group["id"]

    admin_view = client.get("/api/admin/groups", headers=admin_headers)
    assert admin_view.status_code == 200
    assert admin_view.json()[0]["pending_invitation_count"] == 1

    forbidden_accept = client.post(
        f"/api/workspace/group-invitations/{invitation['membership_id']}/accept",
        headers=charlie_headers,
    )
    assert forbidden_accept.status_code == 403

    duplicate_invite = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    )
    assert duplicate_invite.status_code == 409
    assert duplicate_invite.json()["detail"] == "该用户已有待确认邀请"

    accept_response = client.post(
        f"/api/workspace/group-invitations/{invitation['membership_id']}/accept",
        headers=bob_headers,
    )
    assert accept_response.status_code == 200
    assert {member["username"] for member in accept_response.json()["members"]} == {
        "invite-alice",
        "invite-bob",
    }
    assert [item["name"] for item in client.get("/api/workspace/groups/options", headers=bob_headers).json()] == [
        "邀请状态组"
    ]

    repeated_accept = client.post(
        f"/api/workspace/group-invitations/{invitation['membership_id']}/accept",
        headers=bob_headers,
    )
    assert repeated_accept.status_code == 409

    active_duplicate = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    )
    assert active_duplicate.status_code == 409
    assert active_duplicate.json()["detail"] == "该用户已是已确认成员"

    remove_response = client.delete(
        f"/api/workspace/groups/{group['id']}/members/{bob['id']}",
        headers=alice_headers,
    )
    assert remove_response.status_code == 200
    assert client.get("/api/workspace/groups", headers=bob_headers).json() == []

    reinvite = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    )
    assert reinvite.status_code == 200
    reinvitation = client.get("/api/workspace/group-invitations", headers=bob_headers).json()[0]
    reject_response = client.post(
        f"/api/workspace/group-invitations/{reinvitation['membership_id']}/reject",
        headers=bob_headers,
    )
    assert reject_response.status_code == 200
    assert client.get("/api/workspace/group-invitations", headers=bob_headers).json() == []

    repeated_reject = client.post(
        f"/api/workspace/group-invitations/{reinvitation['membership_id']}/reject",
        headers=bob_headers,
    )
    assert repeated_reject.status_code == 409

    assert client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    ).status_code == 200
    cancelled_invitation = client.get("/api/workspace/group-invitations", headers=bob_headers).json()[0]
    cancel_response = client.post(
        f"/api/workspace/groups/{group['id']}/invitations/{bob['id']}/cancel",
        headers=alice_headers,
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["pending_invitation_count"] == 0
    assert client.post(
        f"/api/workspace/group-invitations/{cancelled_invitation['membership_id']}/accept",
        headers=bob_headers,
    ).status_code == 409


def test_group_leader_transfer_requires_active_member(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "leader-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "leader-bob", "bob-pass")
    alice_headers = auth_headers(client, "leader-alice", "alice-pass")
    bob_headers = auth_headers(client, "leader-bob", "bob-pass")

    group = client.post(
        "/api/workspace/groups",
        headers=alice_headers,
        json={"name": "组长转移组"},
    ).json()
    assert client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": bob["id"]},
    ).status_code == 200

    pending_transfer = client.put(
        f"/api/workspace/groups/{group['id']}/leader",
        headers=alice_headers,
        json={"leader_user_id": bob["id"]},
    )
    assert pending_transfer.status_code == 422

    accepted_group = accept_group_invitation_record(
        client,
        bob_headers,
        group_id=group["id"],
    )
    transfer_response = client.put(
        f"/api/workspace/groups/{group['id']}/leader",
        headers=alice_headers,
        json={"leader_user_id": bob["id"]},
    )
    assert transfer_response.status_code == 200
    transferred = transfer_response.json()
    assert transferred["leader_user_id"] == bob["id"]
    assert transferred["created_by_user_id"] == alice["id"]
    assert {member["id"] for member in transferred["members"]} == {alice["id"], bob["id"]}
    assert accepted_group["created_by_user_id"] == transferred["created_by_user_id"]

    old_leader_update = client.put(
        f"/api/workspace/groups/{group['id']}",
        headers=alice_headers,
        json={"name": "原组长无权修改"},
    )
    assert old_leader_update.status_code == 403
    new_leader_update = client.put(
        f"/api/workspace/groups/{group['id']}",
        headers=bob_headers,
        json={"name": "新组长已接管"},
    )
    assert new_leader_update.status_code == 200


def test_group_creator_limit_releases_after_delete(client: TestClient):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "quota-user", "quota-pass")
    quota_headers = auth_headers(client, "quota-user", "quota-pass")

    created_groups = []
    for index in range(20):
        response = client.post(
            "/api/workspace/groups",
            headers=quota_headers,
            json={"name": f"配额组-{index:02d}"},
        )
        assert response.status_code == 201
        created_groups.append(response.json())

    overflow = client.post(
        "/api/workspace/groups",
        headers=quota_headers,
        json={"name": "配额组-超限"},
    )
    assert overflow.status_code == 409
    assert overflow.json()["detail"] == "每个用户最多创建 20 个组"

    assert client.delete(
        f"/api/workspace/groups/{created_groups[0]['id']}",
        headers=quota_headers,
    ).status_code == 200
    released = client.post(
        "/api/workspace/groups",
        headers=quota_headers,
        json={"name": "配额组-释放后"},
    )
    assert released.status_code == 201


def test_concurrent_group_creation_never_exceeds_creator_limit(client: TestClient):
    admin_headers = auth_headers(client)
    quota_user = create_user_account(client, admin_headers, "quota-race-user", "quota-race-pass")
    quota_headers = auth_headers(client, "quota-race-user", "quota-race-pass")

    for index in range(19):
        response = client.post(
            "/api/workspace/groups",
            headers=quota_headers,
            json={"name": f"并发配额组-{index:02d}"},
        )
        assert response.status_code == 201

    def create_last_group(index: int) -> int:
        return client.post(
            "/api/workspace/groups",
            headers=quota_headers,
            json={"name": f"并发配额竞争组-{index:02d}"},
        ).status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        status_codes = sorted(executor.map(create_last_group, range(4)))

    assert status_codes.count(201) == 1
    assert status_codes.count(409) == 3
    with engine.begin() as connection:
        group_count = connection.execute(
            text("SELECT COUNT(*) FROM groups WHERE created_by_user_id = :creator_user_id"),
            {"creator_user_id": quota_user["id"]},
        ).scalar_one()
    assert group_count == 20


def test_concurrent_invitation_acceptance_never_exceeds_member_limit(client: TestClient):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "capacity-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "capacity-bob", "bob-pass")
    charlie = create_user_account(client, admin_headers, "capacity-charlie", "charlie-pass")
    dave = create_user_account(client, admin_headers, "capacity-dave", "dave-pass")
    alice_headers = auth_headers(client, "capacity-alice", "alice-pass")
    bob_headers = auth_headers(client, "capacity-bob", "bob-pass")
    charlie_headers = auth_headers(client, "capacity-charlie", "charlie-pass")
    group = client.post(
        "/api/workspace/groups",
        headers=alice_headers,
        json={"name": "容量竞争组"},
    ).json()

    bulk_password_hash = hash_password("capacity-pass")
    with engine.begin() as connection:
        role_id = connection.execute(
            text("SELECT id FROM roles WHERE name = 'USER'")
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO users (username, password_hash, role_id, source, is_active)
                VALUES (:username, :password_hash, :role_id, 'LOCAL', 1)
                """
            ),
            [
                {
                    "username": f"capacity-member-{index:03d}",
                    "password_hash": bulk_password_hash,
                    "role_id": role_id,
                }
                for index in range(98)
            ],
        )
        member_ids = connection.execute(
            text("SELECT id FROM users WHERE username LIKE 'capacity-member-%'")
        ).scalars().all()
        connection.execute(
            text(
                """
                INSERT INTO group_memberships (group_id, user_id, status, created_at)
                VALUES (:group_id, :user_id, 'ACTIVE', CURRENT_TIMESTAMP)
                """
            ),
            [{"group_id": group["id"], "user_id": user_id} for user_id in member_ids],
        )

    for invited_user_id in (bob["id"], charlie["id"]):
        invite_response = client.post(
            f"/api/workspace/groups/{group['id']}/members",
            headers=alice_headers,
            json={"user_id": invited_user_id},
        )
        assert invite_response.status_code == 200

    bob_invitation = client.get("/api/workspace/group-invitations", headers=bob_headers).json()[0]
    charlie_invitation = client.get("/api/workspace/group-invitations", headers=charlie_headers).json()[0]

    def accept_invitation(headers: dict[str, str], membership_id: int) -> int:
        return client.post(
            f"/api/workspace/group-invitations/{membership_id}/accept",
            headers=headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = [
            executor.submit(accept_invitation, bob_headers, bob_invitation["membership_id"]),
            executor.submit(accept_invitation, charlie_headers, charlie_invitation["membership_id"]),
        ]
        status_codes = sorted(future.result() for future in statuses)
    assert status_codes == [200, 409]

    with engine.begin() as connection:
        active_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM group_memberships
                WHERE group_id = :group_id AND status = 'ACTIVE'
                """
            ),
            {"group_id": group["id"]},
        ).scalar_one()
    assert active_count == 100

    full_invite = client.post(
        f"/api/workspace/groups/{group['id']}/members",
        headers=alice_headers,
        json={"user_id": dave["id"]},
    )
    assert full_invite.status_code == 409
    assert full_invite.json()["detail"] == "组成员数量已达 100 人上限"


def test_schema_compatibility_backfills_group_metadata_idempotently(tmp_path: Path):
    legacy_db_path = tmp_path / "legacy-groups.db"
    legacy_engine = create_engine(f"sqlite:///{legacy_db_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE roles (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(32) NOT NULL UNIQUE,
                    description VARCHAR(128) NOT NULL DEFAULT ''
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(64) NOT NULL UNIQUE,
                    password_hash VARCHAR(512) NOT NULL,
                    role_id INTEGER NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE groups (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(128) NOT NULL UNIQUE,
                    description TEXT,
                    leader_user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE group_memberships (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (group_id, user_id)
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO roles (id, name, description) VALUES (1, 'USER', '普通用户')")
        )
        connection.execute(
            text(
                """
                INSERT INTO users (id, username, password_hash, role_id)
                VALUES (1, 'legacy-leader', 'legacy-hash', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO groups (id, name, leader_user_id)
                VALUES (1, '历史组', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO group_memberships (id, group_id, user_id)
                VALUES (1, 1, 1)
                """
            )
        )

    ensure_schema_compatibility(legacy_engine)
    with legacy_engine.begin() as connection:
        connection.execute(
            text("UPDATE group_memberships SET status = 'CANCELLED' WHERE id = 1")
        )
    ensure_schema_compatibility(legacy_engine)

    group_columns = {column["name"] for column in inspect(legacy_engine).get_columns("groups")}
    membership_columns = {
        column["name"] for column in inspect(legacy_engine).get_columns("group_memberships")
    }
    membership_indexes = {
        item["name"] for item in inspect(legacy_engine).get_indexes("group_memberships")
    }
    with legacy_engine.begin() as connection:
        group_row = connection.execute(
            text("SELECT created_by_user_id FROM groups WHERE id = 1")
        ).mappings().one()
        membership_rows = connection.execute(
            text(
                """
                SELECT user_id, status
                FROM group_memberships
                WHERE group_id = 1
                """
            )
        ).mappings().all()

    assert "created_by_user_id" in group_columns
    assert {"status", "invited_by_user_id", "invited_at", "resolved_at"}.issubset(
        membership_columns
    )
    assert {
        "ix_group_memberships_group_status",
        "ix_group_memberships_user_status",
    }.issubset(membership_indexes)
    assert group_row["created_by_user_id"] == 1
    assert membership_rows == [{"user_id": 1, "status": "ACTIVE"}]
    legacy_engine.dispose()


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


def test_upload_accepts_arbitrary_cmd_content(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={"zip_file": ("demo.zip", make_zip("# demo", extra_files={"cmd": "pnpm add demo"}), "application/zip")},
        data={"name": "arbitrary-cmd-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "arbitrary-cmd-skill"


def test_upload_accepts_multiline_cmd_content(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    response = client.post(
        "/api/workspace/skills",
        headers=auth_headers(client),
        files={
            "zip_file": (
                "demo.zip",
                make_zip("# demo", extra_files={"cmd": "npm install -g @xgd/demo-cli\necho done"}),
                "application/zip",
            )
        },
        data={"name": "multiline-cmd-skill", "description_markdown": "# demo"},
    )
    assert response.status_code == 201
    assert response.json()["name"] == "multiline-cmd-skill"


def test_collection_upload_creates_manifest_and_preview(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    response = create_collection_record(
        client,
        monkeypatch,
        headers,
        zip_entries={
            "frontend-design/SKILL.md": "# frontend",
            "frontend-design/references/a.md": "A",
            "code-review/SKILL.md": "# review",
        },
    )

    payload = response.json()
    assert payload["slug"] == "frontend-basic"
    assert payload["current_version"] == "1.0.0"
    assert payload["item_count"] == 2
    assert payload["install_command"] == "npx nexgo-skills@latest install collection frontend-basic"
    assert [item["name"] for item in payload["preview_items"]] == ["code-review", "frontend-design"]
    assert payload["manifest"]["schema_version"] == "nexgo.collection.v1"
    assert payload["manifest"]["package_url"] == "/api/collections/frontend-basic/package?version=1.0.0"

    preview_response = client.post(
        "/api/workspace/collections/preview",
        headers=headers,
        files={
            "zip_file": (
                "preview.zip",
                make_collection_zip({"alpha/SKILL.md": "# alpha", "beta/SKILL.md": "# beta"}),
                "application/zip",
            )
        },
    )
    assert preview_response.status_code == 200
    assert preview_response.json()["item_count"] == 2


def test_collection_upgrade_auto_increments_version(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_response = create_collection_record(client, monkeypatch, headers)
    assert create_response.json()["current_version"] == "1.0.0"

    uploaded_versions: list[str] = []

    def fake_upload(collection_slug: str, collection_version: str, content: bytes) -> str:
        uploaded_versions.append(collection_version)
        return nexus_service.build_collection_package_url(collection_slug, collection_version)

    monkeypatch.setattr(nexus_service, "upload_collection_zip", fake_upload)

    response = client.put(
        "/api/workspace/collections/frontend-basic",
        headers=headers,
        files={
            "zip_file": (
                "frontend-basic-next.zip",
                make_collection_zip({"alpha/SKILL.md": "# alpha next", "gamma/SKILL.md": "# gamma"}),
                "application/zip",
            )
        },
        data={
            "name": "Frontend Basic",
            "description_markdown": "second version",
            "scope_type": "PUBLIC",
            "version": "9.9.9",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert uploaded_versions == ["1.0.1"]
    assert payload["current_version"] == "1.0.1"
    assert payload["manifest"]["version"] == "1.0.1"
    assert [item["version"] for item in payload["version_history"]] == ["1.0.1", "1.0.0"]


def test_collection_zip_validation_rejects_invalid_archives(client: TestClient, monkeypatch):
    headers = auth_headers(client)

    def fake_upload(collection_slug: str, collection_version: str, content: bytes) -> str:
        return nexus_service.build_collection_package_url(collection_slug, collection_version)

    monkeypatch.setattr(nexus_service, "upload_collection_zip", fake_upload)

    cases = [
        (
            {"README.md": "# root", "alpha/SKILL.md": "# alpha"},
            "Skill 集合 ZIP 根目录只能包含 Skill 目录，不能包含普通文件",
        ),
        (
            {"alpha/README.md": "# alpha"},
            "Skill 集合 ZIP 中的 Skill 目录缺少非空 SKILL.md: alpha",
        ),
        (
            {"../evil/SKILL.md": "# evil"},
            "Skill 集合 ZIP 包含不安全路径",
        ),
        (
            {"Alpha/SKILL.md": "# upper", "alpha/SKILL.md": "# lower"},
            "Skill 集合 ZIP 包含重复的 Skill 目录名称",
        ),
    ]

    for index, (entries, detail) in enumerate(cases):
        response = client.post(
            "/api/workspace/collections",
            headers=headers,
            files={"zip_file": (f"bad-{index}.zip", make_collection_zip(entries), "application/zip")},
            data={
                "name": f"Bad {index}",
                "slug": f"bad-{index}",
                "description_markdown": "# bad",
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == detail


def test_collection_group_visibility_protects_manifest_and_package(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        nexus_service,
        "open_package_stream",
        lambda _package_url: nexus_service.NexusPackageStream(iter([b"collection-zip"]), "14"),
    )
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    create_user_account(client, admin_headers, "charlie", "charlie-pass")

    group = create_group_record(client, admin_headers, name="Skill 集合组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")
    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    _, bob_api_key_headers = create_api_key_headers(client, bob_headers)
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
        accept_headers_by_user_id={bob["id"]: bob_headers},
    )

    create_collection_record(
        client,
        monkeypatch,
        alice_headers,
        slug="team-collection",
        name="Team Collection",
        group_id=group["id"],
    )

    anonymous_list = client.get("/api/collections")
    assert anonymous_list.status_code == 200
    assert anonymous_list.json()["items"] == []

    member_list = client.get("/api/collections", headers=bob_headers)
    assert member_list.status_code == 200
    assert [item["slug"] for item in member_list.json()["items"]] == ["team-collection"]

    assert client.get("/api/collections/team-collection/manifest").status_code == 401
    assert client.get("/api/collections/team-collection/manifest", headers=charlie_headers).status_code == 401

    assert client.get("/api/collections/team-collection/manifest", headers=bob_headers).status_code == 401
    manifest_response = client.get("/api/collections/team-collection/manifest", headers=bob_api_key_headers)
    assert manifest_response.status_code == 200
    manifest_payload = manifest_response.json()
    assert manifest_payload["slug"] == "team-collection"
    assert manifest_payload["package_url"] == "/api/collections/team-collection/package?version=1.0.0"

    anonymous_package = client.get("/api/collections/team-collection/package", follow_redirects=False)
    assert anonymous_package.status_code == 401

    assert client.get(
        "/api/collections/team-collection/package",
        headers=bob_headers,
        follow_redirects=False,
    ).status_code == 401

    api_key_package = client.get(
        "/api/collections/team-collection/package",
        headers=bob_api_key_headers,
        follow_redirects=False,
    )
    assert api_key_package.status_code == 200
    assert api_key_package.content == b"collection-zip"


def test_collection_organization_visibility_allows_descendants(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    owner_headers = login_ad_user(
        client,
        monkeypatch,
        "owner",
        distinguished_name=(
            "CN=owner,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    child_headers = login_ad_user(
        client,
        monkeypatch,
        "child",
        distinguished_name=(
            "CN=child,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    sibling_headers = login_ad_user(
        client,
        monkeypatch,
        "sibling",
        distinguished_name=(
            "CN=sibling,OU=终端方案部,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )

    create_collection_record(
        client,
        monkeypatch,
        admin_headers,
        slug="org-collection",
        name="Org Collection",
        scope_type="ORGANIZATION",
        scope_org_level=3,
        scope_org_name="公共技术中心",
        scope_org_path="支付硬件事业群 / 技术中心 / 公共技术中心",
    )

    owner_list = client.get("/api/collections", headers=owner_headers)
    assert owner_list.status_code == 200
    assert [item["slug"] for item in owner_list.json()["items"]] == ["org-collection"]

    child_detail = client.get("/api/collections/org-collection", headers=child_headers)
    assert child_detail.status_code == 200
    assert child_detail.json()["slug"] == "org-collection"

    sibling_detail = client.get("/api/collections/org-collection", headers=sibling_headers)
    assert sibling_detail.status_code == 404


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
        accept_headers_by_user_id={bob["id"]: bob_headers},
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
        data={
            "name": "forbidden-group-skill",
            "description_markdown": "# demo",
            "scope_type": "GROUP",
            "group_id": str(group["id"]),
        },
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["detail"] == "无权将 Skill 绑定到该组"

    allowed_create = client.post(
        "/api/workspace/skills",
        headers=admin_headers,
        files={"zip_file": ("group.zip", make_zip("# group"), "application/zip")},
        data={
            "name": "admin-group-skill",
            "description_markdown": "# demo",
            "scope_type": "GROUP",
            "group_id": str(group["id"]),
        },
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


def test_local_skill_details_rerender_markdown_when_cached_html_is_stale(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    description_markdown = """
| Request | Behavior |
| --- | --- |
| Build docs | Generate a wiki |
""".strip()
    create_local_skill(
        client,
        monkeypatch,
        headers,
        name="table-detail-skill",
        description_markdown=description_markdown,
    )

    stale_html = "<p>legacy cached detail</p>"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE skills SET description_html = :html WHERE name = :name"),
            {"html": stale_html, "name": "table-detail-skill"},
        )

    public_response = client.get("/api/skills/local/table-detail-skill")
    workspace_response = client.get("/api/workspace/skills/table-detail-skill", headers=headers)

    assert public_response.status_code == 200
    assert workspace_response.status_code == 200
    for payload in (public_response.json(), workspace_response.json()):
        assert "<table>" in payload["description_html"]
        assert "<th>Request</th>" in payload["description_html"]
        assert "<td>Generate a wiki</td>" in payload["description_html"]

    with engine.connect() as connection:
        cached_html = connection.execute(
            text("SELECT description_html FROM skills WHERE name = :name"),
            {"name": "table-detail-skill"},
        ).scalar_one()
    assert cached_html == stale_html


def test_local_skill_version_detail_rerenders_version_markdown_when_cache_is_stale(
    client: TestClient,
    monkeypatch,
):
    headers = auth_headers(client)
    description_markdown = """
| Version | Behavior |
| --- | --- |
| 1.0.0 | Original table |
""".strip()
    create_local_skill(
        client,
        monkeypatch,
        headers,
        name="table-history-skill",
        description_markdown=description_markdown,
    )
    update_response = client.put(
        "/api/workspace/skills/table-history-skill",
        headers=headers,
        data={"description_markdown": "second version"},
    )
    assert update_response.status_code == 200

    stale_html = "<p>legacy version cache</p>"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE skill_versions
                SET description_html = :html
                WHERE skill_id = (SELECT id FROM skills WHERE name = :name)
                  AND version = '1.0.0'
                """
            ),
            {"html": stale_html, "name": "table-history-skill"},
        )

    response = client.get("/api/skills/local/table-history-skill/versions/1.0.0")

    assert response.status_code == 200
    payload = response.json()
    assert "<table>" in payload["description_html"]
    assert "<th>Version</th>" in payload["description_html"]
    assert "<td>Original table</td>" in payload["description_html"]

    with engine.connect() as connection:
        cached_html = connection.execute(
            text(
                """
                SELECT description_html
                FROM skill_versions
                WHERE skill_id = (SELECT id FROM skills WHERE name = :name)
                  AND version = '1.0.0'
                """
            ),
            {"name": "table-history-skill"},
        ).scalar_one()
    assert cached_html == stale_html


def test_schema_compatibility_does_not_rewrite_cached_description_html(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_local_skill(client, monkeypatch, headers, name="cache-stability-skill")
    create_collection_record(client, monkeypatch, headers, slug="cache-stability-collection")

    expected = {
        "skills": "<p>skill cache sentinel</p>",
        "skill_versions": "<p>skill version cache sentinel</p>",
        "skill_collections": "<p>collection cache sentinel</p>",
        "skill_collection_snapshots": "<p>collection snapshot cache sentinel</p>",
    }
    with engine.begin() as connection:
        for table_name, value in expected.items():
            connection.execute(text(f"UPDATE {table_name} SET description_html = :html"), {"html": value})

    ensure_schema_compatibility(engine)

    with engine.connect() as connection:
        actual = {
            table_name: connection.execute(text(f"SELECT description_html FROM {table_name} LIMIT 1")).scalar_one()
            for table_name in expected
        }
    assert actual == expected


def test_collection_create_and_update_render_markdown_tables(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_markdown = """
| Skill | Purpose |
| --- | --- |
| alpha | Initial collection |
""".strip()
    create_response = create_collection_record(
        client,
        monkeypatch,
        headers,
        slug="table-collection",
        description_markdown=create_markdown,
    )
    assert "<table>" in create_response.json()["description_html"]
    assert "<td>Initial collection</td>" in create_response.json()["description_html"]

    update_markdown = """
| Skill | Purpose |
| --- | --- |
| beta | Updated collection |
""".strip()
    update_response = client.put(
        "/api/workspace/collections/table-collection",
        headers=headers,
        data={
            "name": "Frontend Basic",
            "description_markdown": update_markdown,
            "scope_type": "PUBLIC",
        },
    )

    assert update_response.status_code == 200
    assert "<table>" in update_response.json()["description_html"]
    assert "<td>Updated collection</td>" in update_response.json()["description_html"]


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
        accept_headers_by_user_id={bob["id"]: bob_headers},
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


def test_organization_scope_options_limit_user_to_leaf_and_admin_to_known_nodes(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice_headers = login_ad_user(
        client,
        monkeypatch,
        "alice",
        distinguished_name=(
            "CN=alice,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )

    user_options = client.get("/api/workspace/organizations/options", headers=alice_headers)
    assert user_options.status_code == 200
    assert user_options.json() == [
        {
            "level": 4,
            "name": "系统方案部",
            "path": "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部",
            "is_leaf": True,
        }
    ]

    admin_options = client.get("/api/workspace/organizations/options", headers=admin_headers)
    assert admin_options.status_code == 200
    assert admin_options.json() == [
        {"level": 1, "name": "支付硬件事业群", "path": "支付硬件事业群", "is_leaf": False},
        {"level": 2, "name": "技术中心", "path": "支付硬件事业群 / 技术中心", "is_leaf": False},
        {
            "level": 3,
            "name": "公共技术中心",
            "path": "支付硬件事业群 / 技术中心 / 公共技术中心",
            "is_leaf": False,
        },
        {
            "level": 4,
            "name": "系统方案部",
            "path": "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部",
            "is_leaf": True,
        },
    ]


def test_organization_scoped_skill_visibility_allows_descendants_and_hides_siblings(
    client: TestClient,
    monkeypatch,
):
    admin_headers = auth_headers(client)
    alice_headers = login_ad_user(
        client,
        monkeypatch,
        "alice",
        distinguished_name=(
            "CN=alice,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    child_headers = login_ad_user(
        client,
        monkeypatch,
        "child",
        distinguished_name=(
            "CN=child,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    sibling_headers = login_ad_user(
        client,
        monkeypatch,
        "sibling",
        distinguished_name=(
            "CN=sibling,OU=终端方案部,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    local_user = create_user_account(client, admin_headers, "localuser", "local-pass")
    local_headers = auth_headers(client, local_user["username"], "local-pass")

    group = create_group_record(client, admin_headers, name="组范围", leader_user_id=local_user["id"])
    replace_group_member_list(
        client,
        local_headers,
        group_id=group["id"],
        user_ids=[local_user["id"]],
    )

    create_local_skill(client, monkeypatch, alice_headers, name="public-skill", scope_type="PUBLIC")
    create_local_skill(
        client,
        monkeypatch,
        local_headers,
        name="group-skill",
        scope_type="GROUP",
        group_id=group["id"],
    )
    create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="org-skill",
        scope_type="ORGANIZATION",
        scope_org_level=3,
        scope_org_name="公共技术中心",
        scope_org_path="支付硬件事业群 / 技术中心 / 公共技术中心",
    )

    owner_list = client.get("/api/skills", headers=alice_headers)
    assert owner_list.status_code == 200
    assert [item["name"] for item in owner_list.json()["local_items"]] == ["org-skill", "public-skill"]

    child_list = client.get("/api/skills", headers=child_headers)
    assert child_list.status_code == 200
    assert [item["name"] for item in child_list.json()["local_items"]] == ["org-skill", "public-skill"]

    sibling_list = client.get("/api/skills", headers=sibling_headers)
    assert sibling_list.status_code == 200
    assert [item["name"] for item in sibling_list.json()["local_items"]] == ["public-skill"]

    local_list = client.get("/api/skills", headers=local_headers)
    assert local_list.status_code == 200
    assert [item["name"] for item in local_list.json()["local_items"]] == ["group-skill", "public-skill"]

    anonymous_list = client.get("/api/skills")
    assert anonymous_list.status_code == 200
    assert [item["name"] for item in anonymous_list.json()["local_items"]] == ["public-skill"]

    child_detail = client.get("/api/skills/local/org-skill", headers=child_headers)
    assert child_detail.status_code == 200
    assert child_detail.json()["name"] == "org-skill"

    child_version = client.get("/api/skills/local/org-skill/versions/1.0.0", headers=child_headers)
    assert child_version.status_code == 200
    assert child_version.json()["version"] == "1.0.0"

    assert client.get("/api/skills/local/org-skill", headers=sibling_headers).status_code == 404
    assert client.get("/api/skills/local/org-skill/versions/1.0.0", headers=sibling_headers).status_code == 404
    assert client.get("/api/skills/local/org-skill", headers=local_headers).status_code == 404
    assert client.get("/api/skills/local/org-skill").status_code == 404


def test_non_admin_can_only_bind_skill_to_current_leaf_organization(client: TestClient, monkeypatch):
    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)

    alice_headers = login_ad_user(
        client,
        monkeypatch,
        "alice",
        distinguished_name=(
            "CN=alice,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )

    forbidden_create = client.post(
        "/api/workspace/skills",
        headers=alice_headers,
        files={"zip_file": ("org.zip", make_zip("# org"), "application/zip")},
        data={
            "name": "ancestor-org-skill",
            "description_markdown": "# demo",
            "scope_type": "ORGANIZATION",
            "scope_org_level": "3",
            "scope_org_name": "公共技术中心",
            "scope_org_path": "支付硬件事业群 / 技术中心 / 公共技术中心",
        },
    )
    assert forbidden_create.status_code == 403
    assert forbidden_create.json()["detail"] == "无权将 Skill 绑定到该组织范围"

    allowed_create = create_local_skill(
        client,
        monkeypatch,
        alice_headers,
        name="leaf-org-skill",
        scope_type="ORGANIZATION",
        scope_org_level=4,
        scope_org_name="系统方案部",
        scope_org_path="支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部",
    )
    payload = allowed_create.json()
    assert payload["scope_type"] == "ORGANIZATION"
    assert payload["scope_org_level"] == 4
    assert payload["scope_org_name"] == "系统方案部"
    assert payload["scope_org_path"] == "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部"


def test_admin_can_bind_skill_to_ancestor_organization_with_partial_depth(
    client: TestClient,
    monkeypatch,
):
    admin_headers = auth_headers(client)
    login_ad_user(
        client,
        monkeypatch,
        "alice",
        distinguished_name="CN=alice,OU=平台研发部,OU=研发中心,OU=新国都集团,DC=xgd,DC=com",
    )
    descendant_headers = login_ad_user(
        client,
        monkeypatch,
        "descendant",
        distinguished_name="CN=descendant,OU=应用一组,OU=平台研发部,OU=研发中心,OU=新国都集团,DC=xgd,DC=com",
    )

    create_response = create_local_skill(
        client,
        monkeypatch,
        admin_headers,
        name="partial-org-skill",
        scope_type="ORGANIZATION",
        scope_org_level=1,
        scope_org_name="研发中心",
        scope_org_path="研发中心",
    )
    assert create_response.json()["scope_org_level"] == 1
    assert create_response.json()["scope_org_path"] == "研发中心"

    descendant_list = client.get("/api/skills", headers=descendant_headers)
    assert descendant_list.status_code == 200
    assert [item["name"] for item in descendant_list.json()["local_items"]] == ["partial-org-skill"]


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
            )
        ], True

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_local_skill(client, monkeypatch, auth_headers(client), name="plm-assistant")

    response = client.get("/api/skills", params={"q": "local"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert payload["local_items"][0]["source"] == "local"
    assert payload["local_items"][0]["install_command"] == "npx nexgo-skills@latest install plm-assistant"
    assert payload["remote_items"][0]["source"] == "skills_sh"
    assert payload["remote_items"][0]["install_command"] is None
    assert payload["remote_error"] is None
    assert payload["remote_has_more"] is True


def test_public_skills_can_skip_remote_search(client: TestClient, monkeypatch):
    remote_called = False

    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        nonlocal remote_called
        remote_called = True
        return [], False

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_local_skill(client, monkeypatch, auth_headers(client), name="plm-assistant")

    response = client.get("/api/skills", params={"q": "local", "include_remote": "false"})
    assert response.status_code == 200

    payload = response.json()
    assert payload["local_items"][0]["name"] == "plm-assistant"
    assert payload["remote_items"] == []
    assert payload["remote_error"] is None
    assert payload["remote_has_more"] is False
    assert remote_called is False


def test_public_local_skills_endpoint_is_local_only(client: TestClient, monkeypatch):
    remote_called = False

    async def fake_search_remote_skills(query: str | None, page: int = 1, page_size: int = 12):
        nonlocal remote_called
        remote_called = True
        return [], False

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    headers = auth_headers(client)
    create_local_skill(client, monkeypatch, headers, name="plm-assistant")
    create_collection_record(client, monkeypatch, headers, slug="frontend-basic", name="Frontend Basic")

    response = client.get("/api/skills/local", params={"q": "local"})
    assert response.status_code == 200

    payload = response.json()
    assert [item["name"] for item in payload["items"]] == ["plm-assistant"]
    assert payload["items"][0]["source"] == "local"
    assert "kind" not in payload["items"][0]
    assert remote_called is False


def test_public_local_library_includes_skills_and_collections(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_local_skill(client, monkeypatch, headers, name="plm-assistant")
    create_collection_record(client, monkeypatch, headers, slug="frontend-basic", name="Frontend Basic")

    response = client.get("/api/local-library")
    assert response.status_code == 200

    items = {(item["kind"], item["slug"]): item for item in response.json()["items"]}
    assert ("skill", "plm-assistant") in items
    assert ("collection", "frontend-basic") in items
    assert items[("skill", "plm-assistant")]["source"] == "local"
    assert items[("skill", "plm-assistant")]["updated_at"] is not None
    collection = items[("collection", "frontend-basic")]
    assert collection["source"] == "collection"
    assert collection["item_count"] == 2
    assert collection["version"] == "1.0.0"
    assert collection["install_command"] == "npx nexgo-skills@latest install collection frontend-basic"


def test_public_local_library_searches_skills_and_collections(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    create_local_skill(
        client,
        monkeypatch,
        headers,
        name="plm-assistant",
        description_markdown="local workflow helper",
    )
    create_collection_record(
        client,
        monkeypatch,
        headers,
        slug="frontend-basic",
        name="Frontend Basic",
        description_markdown="design collection",
    )

    collection_response = client.get("/api/local-library", params={"q": "frontend"})
    assert collection_response.status_code == 200
    assert [(item["kind"], item["slug"]) for item in collection_response.json()["items"]] == [
        ("collection", "frontend-basic")
    ]

    skill_response = client.get("/api/local-library", params={"q": "workflow"})
    assert skill_response.status_code == 200
    assert [(item["kind"], item["slug"]) for item in skill_response.json()["items"]] == [
        ("skill", "plm-assistant")
    ]


def test_public_local_library_hides_unauthorized_collections(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "bob", "bob-pass")
    create_user_account(client, admin_headers, "charlie", "charlie-pass")

    group = create_group_record(client, admin_headers, name="Skill 集合组", leader_user_id=alice["id"])
    alice_headers = auth_headers(client, "alice", "alice-pass")
    bob_headers = auth_headers(client, "bob", "bob-pass")
    charlie_headers = auth_headers(client, "charlie", "charlie-pass")
    replace_group_member_list(
        client,
        alice_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
        accept_headers_by_user_id={bob["id"]: bob_headers},
    )

    create_collection_record(
        client,
        monkeypatch,
        alice_headers,
        slug="team-collection",
        name="Team Collection",
        group_id=group["id"],
    )

    anonymous_response = client.get("/api/local-library")
    assert anonymous_response.status_code == 200
    assert anonymous_response.json()["items"] == []

    member_response = client.get("/api/local-library", headers=bob_headers)
    assert member_response.status_code == 200
    assert [(item["kind"], item["slug"]) for item in member_response.json()["items"]] == [
        ("collection", "team-collection")
    ]

    outsider_response = client.get("/api/local-library", headers=charlie_headers)
    assert outsider_response.status_code == 200
    assert outsider_response.json()["items"] == []


def test_public_skills_sh_endpoint_returns_remote_only(client: TestClient, monkeypatch):
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
            )
        ], False

    monkeypatch.setattr(public_api, "search_remote_skills", fake_search_remote_skills)

    create_local_skill(client, monkeypatch, auth_headers(client), name="plm-assistant")

    response = client.get("/api/skills/skills_sh", params={"q": "design", "page": 2, "page_size": 6})
    assert response.status_code == 200

    payload = response.json()
    assert payload["items"][0]["source"] == "skills_sh"
    assert payload["items"][0]["slug"] == "vercel-labs/agent-skills/ui-ux-pro-max"
    assert payload["items"][0]["install_command"] is None
    assert payload["error"] is None
    assert payload["page"] == 2
    assert payload["page_size"] == 6
    assert payload["has_more"] is False


def test_public_remote_detail_uses_source_and_slug(client: TestClient, monkeypatch):
    async def fake_remote_detail(slug: str):
        assert slug == "vercel-labs/agent-skills/frontend-design"
        return RegistrySkillDetail(
            slug=slug,
            name="frontend-design",
            source="vercel-labs/agent-skills",
            installs=4321,
            description_html="<p>Remote detail</p>",
            detail_url="https://skills.sh/vercel-labs/agent-skills/frontend-design",
        )

    monkeypatch.setattr(public_api, "get_remote_skill_detail", fake_remote_detail)

    response = client.get("/api/skills/skills_sh/vercel-labs/agent-skills/frontend-design")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "skills_sh"
    assert payload["source_repository"] == "vercel-labs/agent-skills"
    assert payload["install_command"] is None
    assert payload["detail_url"] == "https://skills.sh/vercel-labs/agent-skills/frontend-design"
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
    assert payload["local_items"][0]["install_command"] == "npx nexgo-skills@latest install demo-skill"
    assert payload["remote_items"] == []
    assert payload["remote_error"] == "skills.sh 数据暂时不可用，请稍后重试。"


def test_public_config_returns_cli_install_command(client: TestClient, monkeypatch):
    monkeypatch.setenv("NEXGO_SKILLS_INSTALL_COMMAND", "internal-cli add")
    get_settings.cache_clear()
    try:
        response = client.get("/api/public-config")
        assert response.status_code == 200
        command = response.json()["cli_install_command"]
        assert command == "internal-cli add --help"
    finally:
        monkeypatch.delenv("NEXGO_SKILLS_INSTALL_COMMAND", raising=False)
        get_settings.cache_clear()


def test_nexgo_skills_install_command_configures_all_install_commands(client: TestClient, monkeypatch):
    monkeypatch.setenv("NEXGO_SKILLS_INSTALL_COMMAND", "internal-cli add")
    get_settings.cache_clear()

    try:
        assert skill_service.get_install_command("demo-skill") == "internal-cli add demo-skill"
        assert collection_service.get_collection_install_command("frontend-basic") == (
            "internal-cli add collection frontend-basic"
        )

        headers = auth_headers(client)
        skill_response = create_local_skill(client, monkeypatch, headers, name="demo-skill")
        assert skill_response.json()["install_command"] == "internal-cli add demo-skill"

        create_response = create_collection_record(client, monkeypatch, headers)
        expected_command = "internal-cli add collection frontend-basic"
        assert create_response.json()["install_command"] == expected_command

        public_list = client.get("/api/collections")
        assert public_list.status_code == 200
        assert public_list.json()["items"][0]["install_command"] == expected_command

        public_detail = client.get("/api/collections/frontend-basic")
        assert public_detail.status_code == 200
        assert public_detail.json()["install_command"] == expected_command

        local_library = client.get("/api/local-library")
        assert local_library.status_code == 200
        collection_items = [item for item in local_library.json()["items"] if item["kind"] == "collection"]
        assert collection_items[0]["install_command"] == expected_command
    finally:
        monkeypatch.delenv("NEXGO_SKILLS_INSTALL_COMMAND", raising=False)
        get_settings.cache_clear()


def test_skill_install_command_default_uses_latest_npm_package(monkeypatch):
    monkeypatch.delenv("NEXGO_SKILLS_INSTALL_COMMAND", raising=False)
    get_settings.cache_clear()

    try:
        assert skill_service.get_install_command("demo-skill") == (
            "npx nexgo-skills@latest install demo-skill"
        )
        assert collection_service.get_collection_install_command("frontend-basic") == (
            "npx nexgo-skills@latest install collection frontend-basic"
        )
    finally:
        get_settings.cache_clear()


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
    assert payload["remote_items"][0]["install_command"] is None


def test_schema_compatibility_adds_api_key_support_for_legacy_user():
    legacy_db = Path(__file__).with_name("legacy-api-key.db")
    if legacy_db.exists():
        legacy_db.unlink()

    legacy_engine = create_engine(
        f"sqlite:///{legacy_db.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    try:
        with legacy_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE roles (
                        id INTEGER NOT NULL PRIMARY KEY,
                        name VARCHAR(32) NOT NULL UNIQUE,
                        description VARCHAR(128) NOT NULL DEFAULT ''
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE users (
                        id INTEGER NOT NULL PRIMARY KEY,
                        username VARCHAR(64) NOT NULL UNIQUE,
                        password_hash VARCHAR(512) NOT NULL,
                        role_id INTEGER NOT NULL,
                        source VARCHAR(16) NOT NULL DEFAULT 'LOCAL',
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(role_id) REFERENCES roles (id)
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO roles (id, name, description) VALUES (1, 'ADMIN', '管理员'), (2, 'USER', '普通用户')")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users (id, username, password_hash, role_id, source, is_active)
                    VALUES (10, 'legacy-user', :password_hash, 2, 'LOCAL', 1)
                    """
                ),
                {"password_hash": hash_password("legacy-pass")},
            )

        ensure_schema_compatibility(legacy_engine)
        ensure_schema_compatibility(legacy_engine)

        columns = {column["name"] for column in inspect(legacy_engine).get_columns("users")}
        assert {"api_key_hash", "api_key_suffix", "api_key_issued_at"}.issubset(columns)
        with legacy_engine.connect() as connection:
            index_rows = connection.execute(text("PRAGMA index_list('users')")).mappings().all()
            api_key_index = next(row for row in index_rows if row["name"] == "uq_users_api_key_hash")
            legacy_row = connection.execute(
                text(
                    """
                    SELECT api_key_hash, api_key_suffix, api_key_issued_at
                    FROM users
                    WHERE username = 'legacy-user'
                    """
                )
            ).mappings().one()
        assert api_key_index["unique"] == 1
        assert api_key_index["partial"] == 1
        assert legacy_row == {
            "api_key_hash": None,
            "api_key_suffix": None,
            "api_key_issued_at": None,
        }

        legacy_app = FastAPI()
        legacy_app.include_router(auth_router)

        def override_get_db():
            with Session(legacy_engine) as session:
                yield session

        legacy_app.dependency_overrides[get_db] = override_get_db
        with TestClient(legacy_app) as legacy_client:
            login_response = legacy_client.post(
                "/api/auth/login",
                json={"username": "legacy-user", "password": "legacy-pass"},
            )
            assert login_response.status_code == 200
            jwt_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

            create_response = legacy_client.post("/api/auth/api-key", headers=jwt_headers)
            assert create_response.status_code == 201
            assert create_response.json()["api_key"].startswith("ns-")
    finally:
        legacy_engine.dispose()
        if legacy_db.exists():
            legacy_db.unlink()


def test_api_key_lifecycle_plaintext_storage_rotation_and_user_state(client: TestClient):
    admin_headers = auth_headers(client)
    user = create_user_account(client, admin_headers, "api-user", "api-pass")
    user_headers = auth_headers(client, "api-user", "api-pass")

    initial_status = client.get("/api/auth/api-key", headers=user_headers)
    assert initial_status.status_code == 200
    assert initial_status.json() == {"has_api_key": False, "masked_key": None, "issued_at": None}

    rotate_without_key = client.post("/api/auth/api-key/rotate", headers=user_headers)
    assert rotate_without_key.status_code == 409

    issued_payload, api_key_headers = create_api_key_headers(client, user_headers)
    plaintext = issued_payload["api_key"]
    assert plaintext.startswith("ns-")
    assert issued_payload["masked_key"].endswith(plaintext[-8:])

    duplicate_create = client.post("/api/auth/api-key", headers=user_headers)
    assert duplicate_create.status_code == 409
    assert "api_key" not in duplicate_create.json()

    status_response = client.get("/api/auth/api-key", headers=user_headers)
    assert status_response.status_code == 200
    assert status_response.json()["has_api_key"] is True
    assert "api_key" not in status_response.json()
    assert status_response.json()["masked_key"].endswith(plaintext[-8:])
    assert client.get("/api/auth/api-key", headers=api_key_headers).status_code == 401

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT api_key_hash, api_key_suffix
                FROM users
                WHERE username = 'api-user'
                """
            )
        ).mappings().one()
    assert stored["api_key_hash"] != plaintext
    assert len(stored["api_key_hash"]) == 64
    assert stored["api_key_suffix"] == plaintext[-8:]

    rotate_response = client.post("/api/auth/api-key/rotate", headers=user_headers)
    assert rotate_response.status_code == 200
    assert rotate_response.headers["cache-control"] == "no-store"
    rotated_plaintext = rotate_response.json()["api_key"]
    assert rotated_plaintext != plaintext
    assert client.get("/api/skills/local", headers=api_key_headers).status_code == 401

    rotated_headers = {"Authorization": f"Bearer {rotated_plaintext}"}
    assert client.get("/api/skills/local", headers=rotated_headers).status_code == 200

    disable_response = client.put(
        f"/api/admin/users/{user['id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert disable_response.status_code == 200
    assert client.get("/api/skills/local", headers=rotated_headers).status_code == 401
    assert not hasattr(auth_api, "_record_login_credentials")


def test_ad_user_can_create_api_key(client: TestClient, monkeypatch):
    ad_headers = login_ad_user(
        client,
        monkeypatch,
        "api-ad-user",
        distinguished_name="CN=api-ad-user,OU=平台研发部,OU=研发中心,OU=新国都集团,DC=xgd,DC=com",
    )

    issued_payload, api_key_headers = create_api_key_headers(client, ad_headers)
    assert issued_payload["api_key"].startswith("ns-")
    assert client.get("/api/skills/local", headers=api_key_headers).status_code == 200


@pytest.mark.parametrize(
    "authorization",
    ["Basic abc", "Bearer", "Bearer invalid-jwt", "Bearer ns-invalid"],
)
def test_optional_resource_auth_rejects_invalid_authorization(client: TestClient, authorization: str):
    response = client.get("/api/skills/local", headers={"Authorization": authorization})
    assert response.status_code == 401


def test_api_key_workspace_crud_and_jwt_only_boundaries(client: TestClient, monkeypatch):
    admin_jwt_headers = auth_headers(client)
    alice = create_user_account(client, admin_jwt_headers, "api-alice", "alice-pass")
    create_user_account(client, admin_jwt_headers, "api-bob", "bob-pass")
    alice_jwt_headers = auth_headers(client, "api-alice", "alice-pass")
    bob_jwt_headers = auth_headers(client, "api-bob", "bob-pass")
    _, alice_key_headers = create_api_key_headers(client, alice_jwt_headers)
    _, bob_key_headers = create_api_key_headers(client, bob_jwt_headers)
    _, admin_key_headers = create_api_key_headers(client, admin_jwt_headers)

    assert client.get("/api/admin/users", headers=alice_key_headers).status_code == 401
    assert client.get("/api/workspace/groups", headers=alice_key_headers).status_code == 401
    assert client.get("/api/auth/api-key", headers=alice_key_headers).status_code == 401

    skill_response = create_local_skill(
        client,
        monkeypatch,
        alice_key_headers,
        name="api-key-skill",
        description_markdown="created by api key",
    )
    assert skill_response.json()["owner_username"] == "api-alice"
    public_detail = client.get("/api/skills/local/api-key-skill")
    assert public_detail.status_code == 200
    assert public_detail.json()["package_url"] == "/api/skills/local/api-key-skill/package"
    assert "nexus" not in public_detail.text.lower()

    assert client.get("/api/workspace/skills/api-key-skill", headers=bob_key_headers).status_code == 404
    assert client.get("/api/workspace/skills/api-key-skill", headers=admin_key_headers).status_code == 200

    update_skill_response = client.put(
        "/api/workspace/skills/api-key-skill",
        headers=alice_key_headers,
        data={"description_markdown": "updated by api key", "scope_type": "PUBLIC"},
    )
    assert update_skill_response.status_code == 200
    assert "updated by api key" in update_skill_response.json()["description_markdown"]

    preview_response = client.post(
        "/api/workspace/collections/preview",
        headers=alice_key_headers,
        files={
            "zip_file": (
                "preview.zip",
                make_collection_zip({"alpha/SKILL.md": "# alpha"}),
                "application/zip",
            )
        },
    )
    assert preview_response.status_code == 200

    collection_response = create_collection_record(
        client,
        monkeypatch,
        alice_key_headers,
        slug="api-key-collection",
        name="API Key Collection",
    )
    assert collection_response.json()["owner_username"] == "api-alice"
    assert client.get(
        "/api/workspace/collections/api-key-collection",
        headers=bob_key_headers,
    ).status_code == 404
    assert client.get(
        "/api/workspace/collections/api-key-collection",
        headers=admin_key_headers,
    ).status_code == 200

    update_collection_response = client.put(
        "/api/workspace/collections/api-key-collection",
        headers=alice_key_headers,
        data={
            "name": "API Key Collection Updated",
            "description_markdown": "updated collection",
            "scope_type": "PUBLIC",
        },
    )
    assert update_collection_response.status_code == 200
    assert update_collection_response.json()["current_version"] == "1.0.0"

    assert client.delete(
        "/api/workspace/collections/api-key-collection",
        headers=alice_key_headers,
    ).status_code == 200
    assert client.delete(
        "/api/workspace/skills/api-key-skill",
        headers=alice_key_headers,
    ).status_code == 200
    assert alice["username"] == "api-alice"


def test_api_key_group_visibility_uses_current_membership(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "group-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "group-bob", "bob-pass")
    create_user_account(client, admin_headers, "group-charlie", "charlie-pass")
    alice_jwt_headers = auth_headers(client, "group-alice", "alice-pass")
    bob_jwt_headers = auth_headers(client, "group-bob", "bob-pass")
    charlie_jwt_headers = auth_headers(client, "group-charlie", "charlie-pass")
    _, alice_key_headers = create_api_key_headers(client, alice_jwt_headers)
    _, bob_key_headers = create_api_key_headers(client, bob_jwt_headers)
    _, charlie_key_headers = create_api_key_headers(client, charlie_jwt_headers)

    group = create_group_record(client, admin_headers, name="API Key 可见组", leader_user_id=alice["id"])
    replace_group_member_list(
        client,
        alice_jwt_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
    )

    create_local_skill(
        client,
        monkeypatch,
        alice_key_headers,
        name="group-api-skill",
        group_id=group["id"],
    )
    create_collection_record(
        client,
        monkeypatch,
        alice_key_headers,
        slug="group-api-collection",
        name="Group API Collection",
        group_id=group["id"],
    )

    for pending_headers in (bob_jwt_headers, bob_key_headers):
        assert client.get("/api/skills/local/group-api-skill", headers=pending_headers).status_code == 404
        assert client.get("/api/collections/group-api-collection", headers=pending_headers).status_code == 404
        pending_library = client.get("/api/local-library", headers=pending_headers)
        assert pending_library.status_code == 200
        assert not {
            "group-api-skill",
            "group-api-collection",
        }.intersection(item["slug"] for item in pending_library.json()["items"])

    accept_group_invitation_record(client, bob_jwt_headers, group_id=group["id"])
    bob_library = client.get("/api/local-library", headers=bob_key_headers)
    assert bob_library.status_code == 200
    assert {item["slug"] for item in bob_library.json()["items"]} == {
        "group-api-skill",
        "group-api-collection",
    }
    assert client.get("/api/skills/local/group-api-skill", headers=charlie_key_headers).status_code == 404
    assert client.get("/api/collections/group-api-collection", headers=charlie_key_headers).status_code == 404

    replace_group_member_list(
        client,
        alice_jwt_headers,
        group_id=group["id"],
        user_ids=[alice["id"]],
    )
    assert client.get("/api/skills/local/group-api-skill", headers=bob_key_headers).status_code == 404
    assert client.get("/api/collections/group-api-collection", headers=bob_key_headers).status_code == 404


def test_api_key_organization_visibility_matches_jwt(client: TestClient, monkeypatch):
    owner_jwt_headers = login_ad_user(
        client,
        monkeypatch,
        "org-owner",
        distinguished_name=(
            "CN=org-owner,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    child_jwt_headers = login_ad_user(
        client,
        monkeypatch,
        "org-child",
        distinguished_name=(
            "CN=org-child,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    sibling_jwt_headers = login_ad_user(
        client,
        monkeypatch,
        "org-sibling",
        distinguished_name=(
            "CN=org-sibling,OU=终端方案部,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
        ),
    )
    _, owner_key_headers = create_api_key_headers(client, owner_jwt_headers)
    _, child_key_headers = create_api_key_headers(client, child_jwt_headers)
    _, sibling_key_headers = create_api_key_headers(client, sibling_jwt_headers)

    create_local_skill(
        client,
        monkeypatch,
        owner_key_headers,
        name="org-api-skill",
        scope_type="ORGANIZATION",
        scope_org_level=3,
        scope_org_name="公共技术中心",
        scope_org_path="支付硬件事业群 / 技术中心 / 公共技术中心",
    )
    create_collection_record(
        client,
        monkeypatch,
        owner_key_headers,
        slug="org-api-collection",
        name="Org API Collection",
        scope_type="ORGANIZATION",
        scope_org_level=3,
        scope_org_name="公共技术中心",
        scope_org_path="支付硬件事业群 / 技术中心 / 公共技术中心",
    )

    assert client.get("/api/skills/local/org-api-skill", headers=child_key_headers).status_code == 200
    assert client.get("/api/collections/org-api-collection", headers=child_key_headers).status_code == 200
    assert client.get("/api/skills/local/org-api-skill", headers=sibling_key_headers).status_code == 404
    assert client.get("/api/collections/org-api-collection", headers=sibling_key_headers).status_code == 404


def test_application_streams_skill_and_collection_packages_without_nexus_leak(client: TestClient, monkeypatch):
    headers = auth_headers(client)
    _, api_key_headers = create_api_key_headers(client, headers)
    create_local_skill(client, monkeypatch, headers, name="download-skill")
    create_collection_record(
        client,
        monkeypatch,
        headers,
        slug="download-collection",
        name="Download Collection",
    )

    uploaded_versions: list[str] = []

    def fake_upload(collection_slug: str, collection_version: str, content: bytes) -> str:
        uploaded_versions.append(collection_version)
        return nexus_service.build_collection_package_url(collection_slug, collection_version)

    monkeypatch.setattr(nexus_service, "upload_collection_zip", fake_upload)
    update_response = client.put(
        "/api/workspace/collections/download-collection",
        headers=headers,
        files={
            "zip_file": (
                "download-next.zip",
                make_collection_zip({"beta/SKILL.md": "# beta"}),
                "application/zip",
            )
        },
        data={
            "name": "Download Collection",
            "description_markdown": "next",
            "scope_type": "PUBLIC",
        },
    )
    assert update_response.status_code == 200
    assert uploaded_versions == ["1.0.1"]

    requested_urls: list[str] = []

    def fake_open(package_url: str):
        requested_urls.append(package_url)
        payload = f"zip:{package_url.rsplit('/', 1)[-1]}".encode()
        return nexus_service.NexusPackageStream(iter([payload]), str(len(payload)))

    monkeypatch.setattr(nexus_service, "open_package_stream", fake_open)

    skill_response = client.get("/api/skills/local/download-skill/package", headers=api_key_headers)
    assert skill_response.status_code == 200
    assert skill_response.headers["content-type"] == "application/zip"
    assert "download-skill-1.0.0.zip" in skill_response.headers["content-disposition"]
    assert "location" not in skill_response.headers
    assert "nexus" not in skill_response.text.lower()

    current_collection = client.get("/api/collections/download-collection/package", headers=api_key_headers)
    historical_collection = client.get(
        "/api/collections/download-collection/package",
        params={"version": "1.0.0"},
        headers=api_key_headers,
    )
    assert current_collection.status_code == 200
    assert historical_collection.status_code == 200
    assert requested_urls[-2].endswith("/download-collection/1.0.1.zip")
    assert requested_urls[-1].endswith("/download-collection/1.0.0.zip")
    assert all("location" not in response.headers for response in [current_collection, historical_collection])
    assert all("tester" not in response.text for response in [skill_response, current_collection, historical_collection])

    invalid_auth = client.get(
        "/api/skills/local/download-skill/package",
        headers={"Authorization": "Bearer ns-invalid"},
    )
    assert invalid_auth.status_code == 401

    def fail_open(_package_url: str):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="从 Nexus 读取压缩包失败")

    monkeypatch.setattr(nexus_service, "open_package_stream", fail_open)
    upstream_error = client.get("/api/collections/download-collection/package", headers=api_key_headers)
    assert upstream_error.status_code == 502
    assert "nexus.example.invalid" not in upstream_error.text
    assert "tester" not in upstream_error.text


@pytest.mark.parametrize(
    "package_url",
    [
        "https://example.invalid/package.zip",
        "http://nexus.example.invalid:8081/repository/raw-repo/skills/../admin.zip",
        "http://nexus.example.invalid:8081/repository/raw-repo/skills/%252e%252e/admin.zip",
        "http://tester:secret@nexus.example.invalid:8081/repository/raw-repo/skills/demo.zip",
        "http://nexus.example.invalid:bad/repository/raw-repo/skills/demo.zip",
    ],
)
def test_nexus_stream_rejects_untrusted_package_targets(package_url: str):
    with pytest.raises(HTTPException) as exc_info:
        nexus_service.open_package_stream(package_url)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Nexus 压缩包地址不合法"


def test_mcp_entrypoint_coexists_with_openapi_and_exposes_stable_catalog(client: TestClient):
    initialize_response = mcp_rpc(
        client,
        1,
        "initialize",
        {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    )
    assert initialize_response.status_code == 200
    assert initialize_response.json()["result"]["serverInfo"]["name"] == "nexgo-skills"

    catalog_response = mcp_rpc(client, 2, "tools/list")
    assert catalog_response.status_code == 200
    tools = catalog_response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == set(MCP_TOOL_NAMES)
    assert all(tool.get("outputSchema") for tool in tools)

    tools_by_name = {tool["name"]: tool for tool in tools}
    assert tools_by_name["nexgo_skills_search"]["annotations"]["readOnlyHint"] is True
    assert tools_by_name["nexgo_collection_preview"]["annotations"]["readOnlyHint"] is True
    assert tools_by_name["nexgo_skill_delete"]["annotations"]["destructiveHint"] is True
    assert tools_by_name["nexgo_collection_delete"]["annotations"]["destructiveHint"] is True

    invalid_input_response = mcp_call(
        client,
        3,
        "nexgo_skills_search",
        {"page": 0},
    )
    invalid_input_result = invalid_input_response.json()["result"]
    assert invalid_input_result["isError"] is True
    assert invalid_input_result["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

    assert mcp_rpc(client, 4, "tools/list", headers={"Host": "evil.example"}).status_code == 421
    assert mcp_rpc(client, 5, "tools/list", headers={"Origin": "https://evil.example"}).status_code == 403

    openapi_response = client.get("/openapi.json")
    assert openapi_response.status_code == 200
    assert set(openapi_response.json()["paths"]) == {
        "/api/local-library",
        "/api/skills/local",
        "/api/collections",
        "/api/collections/{slug}/manifest",
        "/api/collections/{slug}/package",
        "/api/collections/{slug}",
        "/api/skills/skills_sh",
        "/api/skills",
        "/api/skills/local/{slug}/versions/{version}",
        "/api/skills/local/{slug}/package",
        "/api/skills/{source}/{slug}",
        "/api/workspace/skills",
        "/api/workspace/collections",
        "/api/workspace/collections/preview",
        "/api/workspace/collections/{slug}",
        "/api/workspace/skills/{name}",
    }
    assert client.get("/api/healthcheck").status_code == 200


def test_openapi_documents_all_public_parameters_and_scope_values(client: TestClient):
    schema = client.get("/openapi.json").json()

    missing_descriptions: list[tuple[str, str, str]] = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for parameter in operation.get("parameters", []):
                if not parameter.get("description"):
                    missing_descriptions.append((method, path, parameter["name"]))

            request_body = operation.get("requestBody")
            if not request_body:
                continue
            assert request_body.get("description"), f"{method.upper()} {path} 缺少请求体说明"
            for media_type in request_body["content"].values():
                body_schema = media_type["schema"]
                if "$ref" in body_schema:
                    schema_name = body_schema["$ref"].rsplit("/", 1)[-1]
                    body_schema = schema["components"]["schemas"][schema_name]
                for field_name, field_schema in body_schema.get("properties", {}).items():
                    if not field_schema.get("description"):
                        missing_descriptions.append((method, path, field_name))

    assert missing_descriptions == []

    missing_schema_descriptions: list[str] = []
    missing_schema_field_descriptions: list[tuple[str, str]] = []
    for schema_name, component_schema in schema["components"]["schemas"].items():
        if not component_schema.get("description"):
            missing_schema_descriptions.append(schema_name)
        for field_name, field_schema in component_schema.get("properties", {}).items():
            if not field_schema.get("description"):
                missing_schema_field_descriptions.append((schema_name, field_name))

    assert missing_schema_descriptions == []
    assert missing_schema_field_descriptions == []

    scope_schemas = [
        body_schema["properties"]["scope_type"]
        for schema_name, body_schema in schema["components"]["schemas"].items()
        if schema_name.startswith("Body_") and "scope_type" in body_schema.get("properties", {})
    ]
    assert len(scope_schemas) == 4
    for scope_schema in scope_schemas:
        assert scope_schema["default"] == "PUBLIC"
        assert scope_schema["enum"] == ["PUBLIC", "GROUP", "ORGANIZATION"]
        assert "GROUP" in scope_schema["description"]
        assert "scope_org_level" in scope_schema["description"]

    for schema_name in [
        "ManagedSkillSummary",
        "ManagedCollectionSummary",
        "PublicSkillSummary",
        "PublicCollectionSummary",
    ]:
        scope_schema = schema["components"]["schemas"][schema_name]["properties"]["scope_type"]
        assert "PUBLIC" in scope_schema["description"]
        assert "GROUP" in scope_schema["description"]
        assert "ORGANIZATION" in scope_schema["description"]

    response_scope_schemas = [
        component_schema["properties"]["scope_type"]
        for schema_name, component_schema in schema["components"]["schemas"].items()
        if not schema_name.startswith("Body_")
        and "scope_type" in component_schema.get("properties", {})
    ]
    for scope_schema in response_scope_schemas:
        allows_null = any(option.get("type") == "null" for option in scope_schema.get("anyOf", []))
        expected_values = ["PUBLIC", "GROUP", "ORGANIZATION"]
        if allows_null:
            expected_values.append(None)
        assert scope_schema["enum"] == expected_values

    workspace_parameters = schema["paths"]["/api/workspace/skills"]["get"]["parameters"]
    authorization = next(parameter for parameter in workspace_parameters if parameter["name"] == "Authorization")
    assert authorization["required"] is True
    assert "API Key" in authorization["description"]

    for path in [
        "/api/collections/{slug}/manifest",
        "/api/collections/{slug}/package",
        "/api/skills/local/{slug}/package",
    ]:
        parameters = schema["paths"][path]["get"]["parameters"]
        authorization = next(parameter for parameter in parameters if parameter["name"] == "Authorization")
        assert authorization["required"] is True
        assert "只接受" in authorization["description"]
        assert "JWT" in authorization["description"]


def test_mcp_transport_accepts_only_current_api_key_and_reauthenticates_each_request(client: TestClient):
    jwt_headers = auth_headers(client)
    issued, api_key_headers = create_api_key_headers(client, jwt_headers)
    api_key = issued["api_key"]

    anonymous_result = mcp_call(client, 10, "nexgo_managed_skills_list")
    assert anonymous_result.status_code == 200
    assert anonymous_result.json()["result"]["isError"] is True
    assert anonymous_result.json()["result"]["structuredContent"]["error"]["code"] == "AUTHENTICATION_REQUIRED"

    spoofed_result = mcp_call(
        client,
        11,
        "nexgo_managed_skills_list",
        headers={"X-API-Key": api_key, "Cookie": f"api_key={api_key}"},
        path=f"/mcp?api_key={api_key}",
    )
    assert spoofed_result.status_code == 200
    assert spoofed_result.json()["result"]["structuredContent"]["error"]["code"] == "AUTHENTICATION_REQUIRED"

    for authorization in [jwt_headers["Authorization"], "Basic invalid", "Bearer ns-invalid"]:
        response = mcp_rpc(
            client,
            12,
            "tools/list",
            headers={"Authorization": authorization},
        )
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == 'Bearer realm="nexgo-skills-mcp", error="invalid_token"'
        assert response.headers["cache-control"] == "no-store"

    authenticated_result = mcp_call(
        client,
        13,
        "nexgo_managed_skills_list",
        headers=api_key_headers,
    )
    assert authenticated_result.status_code == 200
    assert authenticated_result.json()["result"]["structuredContent"] == {"ok": True, "data": []}

    rotate_response = client.post("/api/auth/api-key/rotate", headers=jwt_headers)
    assert rotate_response.status_code == 200
    rotated_headers = {"Authorization": f"Bearer {rotate_response.json()['api_key']}"}

    stale_key_response = mcp_rpc(client, 14, "tools/list", headers=api_key_headers)
    assert stale_key_response.status_code == 401
    rotated_key_response = mcp_call(
        client,
        15,
        "nexgo_managed_skills_list",
        headers=rotated_headers,
    )
    assert rotated_key_response.status_code == 200
    assert rotated_key_response.json()["result"]["structuredContent"]["ok"] is True

    inactive_user = create_user_account(client, jwt_headers, "mcp-inactive", "inactive-pass")
    inactive_jwt_headers = auth_headers(client, "mcp-inactive", "inactive-pass")
    _, inactive_key_headers = create_api_key_headers(client, inactive_jwt_headers)
    disable_response = client.put(
        f"/api/admin/users/{inactive_user['id']}",
        headers=jwt_headers,
        json={"is_active": False},
    )
    assert disable_response.status_code == 200
    inactive_key_response = mcp_rpc(client, 16, "tools/list", headers=inactive_key_headers)
    assert inactive_key_response.status_code == 401


def test_mcp_concurrent_requests_keep_principals_isolated(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    create_user_account(client, admin_headers, "mcp-concurrent-alice", "alice-pass")
    create_user_account(client, admin_headers, "mcp-concurrent-bob", "bob-pass")
    alice_jwt_headers = auth_headers(client, "mcp-concurrent-alice", "alice-pass")
    bob_jwt_headers = auth_headers(client, "mcp-concurrent-bob", "bob-pass")
    _, alice_key_headers = create_api_key_headers(client, alice_jwt_headers)
    _, bob_key_headers = create_api_key_headers(client, bob_jwt_headers)

    create_local_skill(client, monkeypatch, alice_key_headers, name="alice-only-skill")
    create_local_skill(client, monkeypatch, bob_key_headers, name="bob-only-skill")

    def list_managed(headers: dict[str, str] | None):
        response = mcp_call(
            client,
            17,
            "nexgo_managed_skills_list",
            headers=headers,
        )
        payload = response.json()
        structured = payload.get("result", {}).get("structuredContent", payload)
        return response.status_code, structured

    requests = [alice_key_headers, bob_key_headers, None] * 6
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(list_managed, requests))

    for headers, (status_code, structured) in zip(requests, results, strict=True):
        assert status_code == 200
        if headers == alice_key_headers:
            assert {item["name"] for item in structured["data"]} == {"alice-only-skill"}
        elif headers == bob_key_headers:
            assert {item["name"] for item in structured["data"]} == {"bob-only-skill"}
        else:
            assert structured["error"]["code"] == "AUTHENTICATION_REQUIRED"

    rotate_response = client.post("/api/auth/api-key/rotate", headers=alice_jwt_headers)
    assert rotate_response.status_code == 200
    rotated_headers = {"Authorization": f"Bearer {rotate_response.json()['api_key']}"}
    with ThreadPoolExecutor(max_workers=2) as executor:
        stale_future = executor.submit(list_managed, alice_key_headers)
        rotated_future = executor.submit(list_managed, rotated_headers)
        stale_status, _ = stale_future.result()
        rotated_status, rotated_structured = rotated_future.result()
    assert stale_status == 401
    assert rotated_status == 200
    assert {item["name"] for item in rotated_structured["data"]} == {"alice-only-skill"}


def test_mcp_transport_rejects_request_body_over_configured_limit(monkeypatch):
    monkeypatch.setattr(get_settings(), "mcp_max_request_body_bytes", 128)
    with TestClient(app) as limited_client:
        response = limited_client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            content=b"x" * 129,
        )
    assert response.status_code == 413
    assert "large" in response.text.lower()


def test_mcp_skill_crud_errors_and_download_descriptor(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    _, admin_key_headers = create_api_key_headers(client, admin_headers)
    create_user_account(client, admin_headers, "mcp-owner", "owner-pass")
    create_user_account(client, admin_headers, "mcp-other", "other-pass")
    owner_jwt_headers = auth_headers(client, "mcp-owner", "owner-pass")
    other_jwt_headers = auth_headers(client, "mcp-other", "other-pass")
    _, owner_key_headers = create_api_key_headers(client, owner_jwt_headers)
    _, other_key_headers = create_api_key_headers(client, other_jwt_headers)

    def fake_upload(skill_name: str, content: bytes) -> str:
        return nexus_service.build_package_url(skill_name)

    monkeypatch.setattr(nexus_service, "upload_skill_zip", fake_upload)
    package_base64 = base64.b64encode(make_zip("# MCP skill")).decode("ascii")
    create_arguments = {
        "name": "mcp-skill",
        "description_markdown": "created through MCP",
        "scope_type": "PUBLIC",
        "package_base64": package_base64,
    }

    create_response = mcp_call(
        client,
        20,
        "nexgo_skill_create",
        create_arguments,
        headers=owner_key_headers,
    )
    assert create_response.status_code == 200
    created = create_response.json()["result"]["structuredContent"]["data"]
    assert created["name"] == "mcp-skill"
    assert created["owner_username"] == "mcp-owner"
    assert created["current_version"] == "1.0.0"

    rest_detail = client.get("/api/workspace/skills/mcp-skill", headers=owner_key_headers)
    assert rest_detail.status_code == 200
    assert rest_detail.json()["id"] == created["id"]

    conflict_response = mcp_call(
        client,
        21,
        "nexgo_skill_create",
        create_arguments,
        headers=owner_key_headers,
    )
    assert conflict_response.json()["result"]["structuredContent"]["error"]["code"] == "CONFLICT"

    invisible_response = mcp_call(
        client,
        22,
        "nexgo_managed_skill_get",
        {"name": "mcp-skill"},
        headers=other_key_headers,
    )
    assert invisible_response.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"

    admin_detail_response = mcp_call(
        client,
        221,
        "nexgo_managed_skill_get",
        {"name": "mcp-skill"},
        headers=admin_key_headers,
    )
    assert admin_detail_response.json()["result"]["structuredContent"]["data"]["id"] == created["id"]

    invalid_scope_response = mcp_call(
        client,
        222,
        "nexgo_skill_create",
        {
            "name": "missing-group-skill",
            "scope_type": "GROUP",
            "package_base64": package_base64,
        },
        headers=owner_key_headers,
    )
    assert invalid_scope_response.json()["result"]["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

    metadata_update = mcp_call(
        client,
        23,
        "nexgo_skill_update",
        {
            "name": "mcp-skill",
            "description_markdown": "metadata only",
            "scope_type": "PUBLIC",
        },
        headers=owner_key_headers,
    )
    metadata_updated = metadata_update.json()["result"]["structuredContent"]["data"]
    assert metadata_updated["current_version"] == "1.0.1"
    assert metadata_updated["description_markdown"] == "metadata only"

    package_update = mcp_call(
        client,
        24,
        "nexgo_skill_update",
        {
            "name": "mcp-skill",
            "description_markdown": "package update",
            "scope_type": "PUBLIC",
            "package_base64": base64.b64encode(make_zip("# updated")).decode("ascii"),
        },
        headers=owner_key_headers,
    )
    assert package_update.json()["result"]["structuredContent"]["data"]["current_version"] == "1.0.2"

    history_response = mcp_call(
        client,
        241,
        "nexgo_skill_get",
        {"slug": "mcp-skill", "version": "1.0.0"},
    )
    history_detail = history_response.json()["result"]["structuredContent"]["data"]
    assert history_detail["version"] == "1.0.0"
    assert history_detail["history_versions"] == ["1.0.2", "1.0.1", "1.0.0"]

    rest_search = client.get("/api/skills", params={"include_remote": "false"})
    mcp_search = mcp_call(
        client,
        242,
        "nexgo_skills_search",
        {"include_remote": False},
    )
    assert {
        item["slug"] for item in rest_search.json()["local_items"]
    } == {
        item["slug"] for item in mcp_search.json()["result"]["structuredContent"]["data"]["local_items"]
    }

    async def fake_remote_search(query: str | None, page: int = 1, page_size: int = 12):
        return [
            RegistrySkillSummary(
                slug="remote-owner/remote-skill",
                name="Remote Skill",
                source="skills_sh",
                installs=42,
                description_html="<p>remote</p>",
            )
        ], False

    async def fake_remote_detail(slug: str):
        return RegistrySkillDetail(
            slug=slug,
            name="Remote Skill",
            source="skills_sh",
            installs=42,
            description_html="<p>remote</p>",
            detail_url="https://skills.sh/remote-owner/remote-skill",
        )

    monkeypatch.setattr(resource_facade, "search_remote_skills", fake_remote_search)
    monkeypatch.setattr(resource_facade, "get_remote_skill_detail", fake_remote_detail)
    remote_search_response = mcp_call(
        client,
        243,
        "nexgo_skills_search",
        {"query": "remote", "include_remote": True},
    )
    remote_items = remote_search_response.json()["result"]["structuredContent"]["data"]["remote_items"]
    assert [item["slug"] for item in remote_items] == ["remote-owner/remote-skill"]
    remote_detail_response = mcp_call(
        client,
        244,
        "nexgo_skill_get",
        {"source": "skills_sh", "slug": "remote-owner/remote-skill"},
    )
    assert remote_detail_response.json()["result"]["structuredContent"]["data"]["installs"] == 42

    download_response = mcp_call(
        client,
        25,
        "nexgo_skill_download",
        {"slug": "mcp-skill"},
    )
    descriptor = download_response.json()["result"]["structuredContent"]["data"]
    assert descriptor == {
        "download_path": "/api/skills/local/mcp-skill/package",
        "filename": "mcp-skill-1.0.2.zip",
        "version": "1.0.2",
        "content_type": "application/zip",
        "requires_api_key": True,
        "resource_uri": None,
    }
    assert "nexus" not in str(descriptor).lower()
    assert "ns-" not in str(descriptor)

    malformed_response = mcp_call(
        client,
        26,
        "nexgo_skill_create",
        {"name": "bad-base64", "package_base64": "%%%"},
        headers=owner_key_headers,
    )
    assert malformed_response.json()["result"]["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

    invalid_zip_response = mcp_call(
        client,
        27,
        "nexgo_skill_create",
        {"name": "bad-zip", "package_base64": base64.b64encode(b"not a zip").decode("ascii")},
        headers=owner_key_headers,
    )
    assert invalid_zip_response.json()["result"]["structuredContent"]["error"]["code"] == "INVALID_ARGUMENT"

    monkeypatch.setattr(get_settings(), "mcp_max_package_bytes", 8)
    oversized_response = mcp_call(
        client,
        28,
        "nexgo_skill_create",
        {"name": "too-large", "package_base64": base64.b64encode(b"123456789").decode("ascii")},
        headers=owner_key_headers,
    )
    assert oversized_response.json()["result"]["structuredContent"]["error"]["code"] == "PACKAGE_TOO_LARGE"
    managed_after_errors = client.get("/api/workspace/skills", headers=owner_key_headers)
    assert {item["name"] for item in managed_after_errors.json()} == {"mcp-skill"}

    delete_response = mcp_call(
        client,
        29,
        "nexgo_skill_delete",
        {"name": "mcp-skill"},
        headers=owner_key_headers,
    )
    assert delete_response.json()["result"]["structuredContent"]["ok"] is True
    missing_response = mcp_call(
        client,
        30,
        "nexgo_skill_get",
        {"slug": "mcp-skill"},
    )
    assert missing_response.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"


def test_mcp_collection_preview_crud_and_versioned_download(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    _, admin_key_headers = create_api_key_headers(client, admin_headers)
    create_user_account(client, admin_headers, "mcp-collection-owner", "owner-pass")
    create_user_account(client, admin_headers, "mcp-collection-other", "other-pass")
    owner_jwt_headers = auth_headers(client, "mcp-collection-owner", "owner-pass")
    other_jwt_headers = auth_headers(client, "mcp-collection-other", "other-pass")
    _, api_key_headers = create_api_key_headers(client, owner_jwt_headers)
    _, other_key_headers = create_api_key_headers(client, other_jwt_headers)

    def fake_upload(collection_slug: str, collection_version: str, content: bytes) -> str:
        return nexus_service.build_collection_package_url(collection_slug, collection_version)

    monkeypatch.setattr(nexus_service, "upload_collection_zip", fake_upload)
    initial_package = base64.b64encode(
        make_collection_zip(
            {
                "alpha/SKILL.md": "# alpha",
                "alpha/references/a.md": "A",
                "beta/SKILL.md": "# beta",
            }
        )
    ).decode("ascii")

    preview_response = mcp_call(
        client,
        40,
        "nexgo_collection_preview",
        {"package_base64": initial_package},
        headers=api_key_headers,
    )
    preview = preview_response.json()["result"]["structuredContent"]["data"]
    assert preview["version"] == "1.0.0"
    assert preview["item_count"] == 2
    assert [item["name"] for item in preview["items"]] == ["alpha", "beta"]
    assert all(item["sha256"] for item in preview["items"])

    create_response = mcp_call(
        client,
        41,
        "nexgo_collection_create",
        {
            "name": "MCP Collection",
            "slug": "mcp-collection",
            "description_markdown": "created through MCP",
            "scope_type": "PUBLIC",
            "package_base64": initial_package,
        },
        headers=api_key_headers,
    )
    created = create_response.json()["result"]["structuredContent"]["data"]
    assert created["current_version"] == "1.0.0"
    assert created["item_count"] == 2
    assert created["owner_username"] == "mcp-collection-owner"

    conflict_response = mcp_call(
        client,
        411,
        "nexgo_collection_create",
        {
            "name": "MCP Collection Duplicate",
            "slug": "mcp-collection",
            "package_base64": initial_package,
        },
        headers=api_key_headers,
    )
    assert conflict_response.json()["result"]["structuredContent"]["error"]["code"] == "CONFLICT"

    other_detail_response = mcp_call(
        client,
        412,
        "nexgo_managed_collection_get",
        {"slug": "mcp-collection"},
        headers=other_key_headers,
    )
    assert other_detail_response.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"
    admin_detail_response = mcp_call(
        client,
        413,
        "nexgo_managed_collection_get",
        {"slug": "mcp-collection"},
        headers=admin_key_headers,
    )
    assert admin_detail_response.json()["result"]["structuredContent"]["data"]["id"] == created["id"]

    metadata_update = mcp_call(
        client,
        42,
        "nexgo_collection_update",
        {
            "slug": "mcp-collection",
            "name": "MCP Collection Renamed",
            "description_markdown": "metadata only",
            "scope_type": "PUBLIC",
        },
        headers=api_key_headers,
    )
    metadata_updated = metadata_update.json()["result"]["structuredContent"]["data"]
    assert metadata_updated["current_version"] == "1.0.0"
    assert metadata_updated["name"] == "MCP Collection Renamed"

    next_package = base64.b64encode(
        make_collection_zip({"gamma/SKILL.md": "# gamma"})
    ).decode("ascii")
    package_update = mcp_call(
        client,
        43,
        "nexgo_collection_update",
        {
            "slug": "mcp-collection",
            "name": "MCP Collection Renamed",
            "description_markdown": "package update",
            "scope_type": "PUBLIC",
            "package_base64": next_package,
        },
        headers=api_key_headers,
    )
    package_updated = package_update.json()["result"]["structuredContent"]["data"]
    assert package_updated["current_version"] == "1.0.1"
    assert [item["version"] for item in package_updated["version_history"]] == ["1.0.1", "1.0.0"]

    manifest_response = mcp_call(
        client,
        44,
        "nexgo_collection_manifest_get",
        {"slug": "mcp-collection", "version": "1.0.0"},
    )
    manifest = manifest_response.json()["result"]["structuredContent"]["data"]
    assert manifest["version"] == "1.0.0"
    assert manifest["package_url"] == "/api/collections/mcp-collection/package?version=1.0.0"

    download_response = mcp_call(
        client,
        45,
        "nexgo_collection_download",
        {"slug": "mcp-collection", "version": "1.0.0"},
    )
    descriptor = download_response.json()["result"]["structuredContent"]["data"]
    assert descriptor["download_path"] == "/api/collections/mcp-collection/package?version=1.0.0"
    assert descriptor["filename"] == "mcp-collection-1.0.0.zip"
    assert descriptor["requires_api_key"] is True
    assert "nexus" not in str(descriptor).lower()

    delete_response = mcp_call(
        client,
        46,
        "nexgo_collection_delete",
        {"slug": "mcp-collection"},
        headers=api_key_headers,
    )
    assert delete_response.json()["result"]["structuredContent"]["ok"] is True
    missing_response = mcp_call(
        client,
        47,
        "nexgo_collection_get",
        {"slug": "mcp-collection"},
    )
    assert missing_response.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"


def test_mcp_visibility_tracks_current_group_membership(client: TestClient, monkeypatch):
    admin_headers = auth_headers(client)
    alice = create_user_account(client, admin_headers, "mcp-group-alice", "alice-pass")
    bob = create_user_account(client, admin_headers, "mcp-group-bob", "bob-pass")
    create_user_account(client, admin_headers, "mcp-group-charlie", "charlie-pass")
    alice_jwt_headers = auth_headers(client, "mcp-group-alice", "alice-pass")
    bob_jwt_headers = auth_headers(client, "mcp-group-bob", "bob-pass")
    charlie_jwt_headers = auth_headers(client, "mcp-group-charlie", "charlie-pass")
    _, alice_key_headers = create_api_key_headers(client, alice_jwt_headers)
    _, bob_key_headers = create_api_key_headers(client, bob_jwt_headers)
    _, charlie_key_headers = create_api_key_headers(client, charlie_jwt_headers)

    group = create_group_record(client, admin_headers, name="MCP 可见组", leader_user_id=alice["id"])
    replace_group_member_list(
        client,
        alice_jwt_headers,
        group_id=group["id"],
        user_ids=[alice["id"], bob["id"]],
    )
    create_local_skill(
        client,
        monkeypatch,
        alice_key_headers,
        name="mcp-group-skill",
        group_id=group["id"],
    )
    create_collection_record(
        client,
        monkeypatch,
        alice_key_headers,
        slug="mcp-group-collection",
        name="MCP Group Collection",
        group_id=group["id"],
    )

    pending_skill = mcp_call(
        client,
        48,
        "nexgo_skill_get",
        {"slug": "mcp-group-skill"},
        headers=bob_key_headers,
    )
    pending_collection = mcp_call(
        client,
        49,
        "nexgo_collection_get",
        {"slug": "mcp-group-collection"},
        headers=bob_key_headers,
    )
    assert pending_skill.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"
    assert pending_collection.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"

    accept_group_invitation_record(client, bob_jwt_headers, group_id=group["id"])
    bob_skill = mcp_call(
        client,
        50,
        "nexgo_skill_get",
        {"slug": "mcp-group-skill"},
        headers=bob_key_headers,
    )
    bob_collection = mcp_call(
        client,
        51,
        "nexgo_collection_get",
        {"slug": "mcp-group-collection"},
        headers=bob_key_headers,
    )
    assert bob_skill.json()["result"]["structuredContent"]["ok"] is True
    assert bob_collection.json()["result"]["structuredContent"]["ok"] is True

    private_download = mcp_call(
        client,
        511,
        "nexgo_skill_download",
        {"slug": "mcp-group-skill"},
        headers=bob_key_headers,
    )
    private_descriptor = private_download.json()["result"]["structuredContent"]["data"]
    assert private_descriptor["requires_api_key"] is True
    assert private_descriptor["download_path"] == "/api/skills/local/mcp-group-skill/package"
    assert "nexus" not in str(private_descriptor).lower()

    anonymous_download = mcp_call(
        client,
        512,
        "nexgo_skill_download",
        {"slug": "mcp-group-skill"},
    )
    assert anonymous_download.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"

    def fake_open(package_url: str):
        payload = b"private-package"
        return nexus_service.NexusPackageStream(iter([payload]), str(len(payload)))

    monkeypatch.setattr(nexus_service, "open_package_stream", fake_open)
    authorized_package = client.get(private_descriptor["download_path"], headers=bob_key_headers)
    anonymous_package = client.get(private_descriptor["download_path"])
    assert authorized_package.status_code == 200
    assert authorized_package.content == b"private-package"
    assert "location" not in authorized_package.headers
    assert anonymous_package.status_code == 401

    rest_library = client.get("/api/local-library", headers=bob_key_headers).json()["items"]
    mcp_search = mcp_call(
        client,
        513,
        "nexgo_skills_search",
        {"include_remote": False},
        headers=bob_key_headers,
    ).json()["result"]["structuredContent"]["data"]["local_items"]
    assert {item["slug"] for item in mcp_search} == {
        item["slug"] for item in rest_library if item["kind"] == "skill"
    }

    for headers in [None, charlie_key_headers]:
        hidden_skill = mcp_call(
            client,
            52,
            "nexgo_skill_get",
            {"slug": "mcp-group-skill"},
            headers=headers,
        )
        hidden_collection = mcp_call(
            client,
            53,
            "nexgo_collection_get",
            {"slug": "mcp-group-collection"},
            headers=headers,
        )
        assert hidden_skill.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"
        assert hidden_collection.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"

    replace_group_member_list(
        client,
        alice_jwt_headers,
        group_id=group["id"],
        user_ids=[alice["id"]],
    )
    stale_membership = mcp_call(
        client,
        54,
        "nexgo_skill_get",
        {"slug": "mcp-group-skill"},
        headers=bob_key_headers,
    )
    assert stale_membership.json()["result"]["structuredContent"]["error"]["code"] == "NOT_FOUND"
