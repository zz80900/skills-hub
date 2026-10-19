import io
import json
import pathlib
import time
import zipfile
from typing import Any

import httpx


BASE = "http://127.0.0.1:8000"
ZIP_PATH = pathlib.Path(r"C:\Users\xiejincheng\.codex\skills\auto-comment\auto-comment.zip")
SOURCE_ZIP = ZIP_PATH.read_bytes()
STAMP = str(int(time.time()))
SKILL_NAME = f"qa-openapi-skill-{STAMP}"
COLLECTION_SLUG = f"qa-openapi-collection-{STAMP}"
COLLECTION_NAME = f"QA OpenAPI Collection {STAMP}"

OPENAPI_TEMPLATES = {
    ("GET", "/api/collections"),
    ("GET", "/api/collections/{slug}"),
    ("GET", "/api/collections/{slug}/manifest"),
    ("GET", "/api/collections/{slug}/package"),
    ("GET", "/api/local-library"),
    ("GET", "/api/skills"),
    ("GET", "/api/skills/{source}/{slug}"),
    ("GET", "/api/skills/local"),
    ("GET", "/api/skills/local/{slug}/package"),
    ("GET", "/api/skills/local/{slug}/versions/{version}"),
    ("GET", "/api/skills/skills_sh"),
    ("GET", "/api/workspace/collections"),
    ("POST", "/api/workspace/collections"),
    ("DELETE", "/api/workspace/collections/{slug}"),
    ("GET", "/api/workspace/collections/{slug}"),
    ("PUT", "/api/workspace/collections/{slug}"),
    ("POST", "/api/workspace/collections/preview"),
    ("GET", "/api/workspace/skills"),
    ("POST", "/api/workspace/skills"),
    ("DELETE", "/api/workspace/skills/{name}"),
    ("GET", "/api/workspace/skills/{name}"),
    ("PUT", "/api/workspace/skills/{name}"),
}

results: list[dict[str, Any]] = []
seen: set[tuple[str, str]] = set()
client = httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=True)
token = ""
headers: dict[str, str] = {}


def record(
    name: str,
    method: str,
    path: str,
    response: httpx.Response | None,
    expected=(200,),
    note="",
    template=None,
):
    status = response.status_code if response is not None else None
    ok = status in expected
    if template:
        seen.add((method.upper(), template))
    entry = {
        "name": name,
        "method": method.upper(),
        "path": path,
        "template": template,
        "status": status,
        "expected": list(expected),
        "ok": ok,
        "bytes": len(response.content) if response is not None else 0,
        "note": note,
    }
    if response is not None and not ok:
        entry["body"] = response.text[:500]
    results.append(entry)
    print(
        f"{'PASS' if ok else 'FAIL'}|{method.upper()}|{path}|status={status}|"
        f"expected={list(expected)}|{note}"
    )
    return response


def call(
    name: str,
    method: str,
    path: str,
    expected=(200,),
    note="",
    template=None,
    **kwargs,
):
    try:
        response = client.request(method, path, **kwargs)
    except Exception as exc:
        if template:
            seen.add((method.upper(), template))
        results.append(
            {
                "name": name,
                "method": method.upper(),
                "path": path,
                "template": template,
                "status": None,
                "expected": list(expected),
                "ok": False,
                "bytes": 0,
                "note": f"{note} exception={exc}",
            }
        )
        print(f"FAIL|{method.upper()}|{path}|status=None|exception={exc}")
        return None
    return record(name, method, path, response, expected, note, template)


def json_or_empty(response):
    if response is None:
        return {}
    try:
        return response.json()
    except Exception:
        return {}


def collection_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(ZIP_PATH, "r") as source, zipfile.ZipFile(
        output, "w", zipfile.ZIP_DEFLATED
    ) as target:
        for info in source.infolist():
            if info.is_dir():
                continue
            target.writestr(f"auto-comment/{info.filename}", source.read(info.filename))
    return output.getvalue()


def assert_body(name, condition, detail):
    ok = bool(condition)
    results.append(
        {
            "name": name,
            "method": "ASSERT",
            "path": "-",
            "template": None,
            "status": 200 if ok else 500,
            "expected": [200],
            "ok": ok,
            "bytes": 0,
            "note": detail,
        }
    )
    print(f"{'PASS' if ok else 'FAIL'}|ASSERT|-|{detail}")


try:
    spec = call("OpenAPI schema", "GET", "/openapi.json", note="schema")
    spec_json = json_or_empty(spec)
    assert_body(
        "OpenAPI operation count",
        len(
            {
                (method.upper(), path)
                for path, item in spec_json.get("paths", {}).items()
                for method in item
                if method.lower() in {"get", "post", "put", "patch", "delete"}
            }
        )
        == len(OPENAPI_TEMPLATES),
        f"schema declares {len(OPENAPI_TEMPLATES)} expected operations",
    )

    login = call(
        "Admin login",
        "POST",
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
        note="setup",
    )
    login_json = json_or_empty(login)
    token = login_json.get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    assert_body("Admin token", bool(token), "default admin token issued")
    call("Current user", "GET", "/api/auth/me", headers=headers, note="setup")
    call("API Key status", "GET", "/api/auth/api-key", headers=headers, note="setup")
    issued = call("API Key create", "POST", "/api/auth/api-key", expected=(201, 409), headers=headers, note="setup; 409 means an existing key is retained")
    rotated = call("API Key rotate", "POST", "/api/auth/api-key/rotate", headers=headers, note="setup")
    assert_body("API Key response", bool(json_or_empty(rotated).get("api_key")), "one-time API Key response after rotation")

    call("List local library", "GET", "/api/local-library", headers=headers, template="/api/local-library")
    call("List local skills", "GET", "/api/skills/local", headers=headers, template="/api/skills/local")
    call("List collections", "GET", "/api/collections", headers=headers, template="/api/collections")
    call(
        "List skills",
        "GET",
        "/api/skills",
        headers=headers,
        template="/api/skills",
        params={"include_remote": "false"},
    )
    call(
        "List skills.sh",
        "GET",
        "/api/skills/skills_sh",
        headers=headers,
        template="/api/skills/skills_sh",
        params={"page": 1, "page_size": 1},
    )

    skill_files = {"zip_file": ("auto-comment.zip", SOURCE_ZIP, "application/zip")}
    skill_form = {
        "name": SKILL_NAME,
        "description_markdown": "QA OpenAPI skill upload.",
        "scope_type": "PUBLIC",
    }
    created_skill = call(
        "Create skill",
        "POST",
        "/api/workspace/skills",
        expected=(201,),
        headers=headers,
        data=skill_form,
        files=skill_files,
        template="/api/workspace/skills",
    )
    skill_json = json_or_empty(created_skill)
    skill_version = skill_json.get("current_version", "1.0.0")
    assert_body("Skill create payload", skill_json.get("name") == SKILL_NAME, "created skill name matches")
    call("List workspace skills", "GET", "/api/workspace/skills", headers=headers, template="/api/workspace/skills")
    call("Get workspace skill", "GET", f"/api/workspace/skills/{SKILL_NAME}", headers=headers, template="/api/workspace/skills/{name}")
    updated_skill = call(
        "Update skill metadata and package",
        "PUT",
        f"/api/workspace/skills/{SKILL_NAME}",
        headers=headers,
        data={"description_markdown": "QA OpenAPI skill updated.", "scope_type": "PUBLIC"},
        files={"zip_file": ("auto-comment-update.zip", SOURCE_ZIP, "application/zip")},
        template="/api/workspace/skills/{name}",
    )
    updated_skill_json = json_or_empty(updated_skill)
    skill_version = updated_skill_json.get("current_version", skill_version)
    call("Get local skill detail", "GET", f"/api/skills/local/{SKILL_NAME}", headers=headers, template="/api/skills/{source}/{slug}")
    call("Get local skill version", "GET", f"/api/skills/local/{SKILL_NAME}/versions/{skill_version}", headers=headers, template="/api/skills/local/{slug}/versions/{version}")
    package = call("Download local skill package", "GET", f"/api/skills/local/{SKILL_NAME}/package", headers=headers, template="/api/skills/local/{slug}/package")
    assert_body("Skill package bytes", package is not None and package.content == SOURCE_ZIP, "downloaded Skill ZIP equals uploaded ZIP")

    collection_bytes = collection_zip()
    preview = call(
        "Preview collection ZIP",
        "POST",
        "/api/workspace/collections/preview",
        headers=headers,
        files={"zip_file": ("qa-collection.zip", collection_bytes, "application/zip")},
        template="/api/workspace/collections/preview",
    )
    assert_body("Collection preview", bool(json_or_empty(preview).get("items")), "preview contains auto-comment item")
    created_collection = call(
        "Create collection",
        "POST",
        "/api/workspace/collections",
        expected=(201,),
        headers=headers,
        data={
            "name": COLLECTION_NAME,
            "slug": COLLECTION_SLUG,
            "description_markdown": "QA OpenAPI collection.",
            "scope_type": "PUBLIC",
        },
        files={"zip_file": ("qa-collection.zip", collection_bytes, "application/zip")},
        template="/api/workspace/collections",
    )
    collection_json = json_or_empty(created_collection)
    collection_version = collection_json.get("current_version", "1.0.0")
    assert_body("Collection create payload", collection_json.get("slug") == COLLECTION_SLUG, "created collection slug matches")
    call("List workspace collections", "GET", "/api/workspace/collections", headers=headers, template="/api/workspace/collections")
    call("Get workspace collection", "GET", f"/api/workspace/collections/{COLLECTION_SLUG}", headers=headers, template="/api/workspace/collections/{slug}")
    updated_collection = call(
        "Update collection metadata and package",
        "PUT",
        f"/api/workspace/collections/{COLLECTION_SLUG}",
        headers=headers,
        data={"name": COLLECTION_NAME + " Updated", "description_markdown": "QA OpenAPI collection updated.", "scope_type": "PUBLIC"},
        files={"zip_file": ("qa-collection-update.zip", collection_bytes, "application/zip")},
        template="/api/workspace/collections/{slug}",
    )
    collection_version = json_or_empty(updated_collection).get("current_version", collection_version)
    call("Get public collection", "GET", f"/api/collections/{COLLECTION_SLUG}", headers=headers, template="/api/collections/{slug}")
    manifest = call("Get collection manifest", "GET", f"/api/collections/{COLLECTION_SLUG}/manifest", headers=headers, params={"version": collection_version}, template="/api/collections/{slug}/manifest")
    assert_body("Collection manifest", bool(json_or_empty(manifest).get("items")), "manifest contains collection item")
    collection_package = call("Download collection package", "GET", f"/api/collections/{COLLECTION_SLUG}/package", headers=headers, params={"version": collection_version}, template="/api/collections/{slug}/package")
    assert_body("Collection package bytes", collection_package is not None and collection_package.content == collection_bytes, "downloaded collection ZIP equals uploaded ZIP")
finally:
    if token:
        call("Delete collection cleanup", "DELETE", f"/api/workspace/collections/{COLLECTION_SLUG}", headers=headers, expected=(200, 404), template="/api/workspace/collections/{slug}", note="cleanup")
        call("Delete skill cleanup", "DELETE", f"/api/workspace/skills/{SKILL_NAME}", headers=headers, expected=(200, 404), template="/api/workspace/skills/{name}", note="cleanup")
    client.close()

missing = sorted(OPENAPI_TEMPLATES - seen)
failed = [item for item in results if not item["ok"]]
print(f"INFO|COVERAGE|expected={len(OPENAPI_TEMPLATES)}|seen={len(OPENAPI_TEMPLATES - set(missing))}|missing={missing}")
print(f"SUMMARY|passed={len(results) - len(failed)}|failed={len(failed)}|total={len(results)}|openapi_missing={len(missing)}")
pathlib.Path("qa_openapi_report.json").write_text(
    json.dumps(
        {
            "base_url": BASE,
            "zip_path": str(ZIP_PATH),
            "skill_name": SKILL_NAME,
            "collection_slug": COLLECTION_SLUG,
            "results": results,
            "missing_openapi_operations": missing,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
raise SystemExit(1 if failed or missing else 0)
