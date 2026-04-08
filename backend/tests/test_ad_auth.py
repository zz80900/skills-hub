from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ad_auth import (
    ActiveDirectoryUnavailableError,
    build_ldap_server_kwargs_candidates,
    create_kerberos_temp_dir,
    parse_ldap_server_url,
)


def test_parse_ldap_server_url_accepts_ldap_scheme():
    assert parse_ldap_server_url("ldap://10.18.8.16:389") == ("10.18.8.16", 389, False)


def test_parse_ldap_server_url_accepts_ldaps_scheme():
    assert parse_ldap_server_url("ldaps://ad.example.com") == ("ad.example.com", 636, True)


def test_parse_ldap_server_url_accepts_bare_host_and_port():
    assert parse_ldap_server_url("10.18.8.16:1389") == ("10.18.8.16", 1389, False)


def test_parse_ldap_server_url_rejects_invalid_scheme():
    try:
        parse_ldap_server_url("http://10.18.8.16:389")
    except ActiveDirectoryUnavailableError as exc:
        assert str(exc) == "invalid ldap url: http://10.18.8.16:389"
    else:
        raise AssertionError("expected ActiveDirectoryUnavailableError")


def test_build_ldap_server_kwargs_candidates_adds_raw_url_fallback():
    assert build_ldap_server_kwargs_candidates("ldap://10.18.8.16:389") == [
        {"host": "10.18.8.16", "port": 389, "use_ssl": False},
        {"host": "ldap://10.18.8.16:389"},
    ]


def test_build_ldap_server_kwargs_candidates_keeps_bare_host_single():
    assert build_ldap_server_kwargs_candidates("10.18.8.16:389") == [
        {"host": "10.18.8.16", "port": 389, "use_ssl": False},
    ]


def test_create_kerberos_temp_dir_is_writable():
    parent_dir = BACKEND_ROOT / "tests" / "local-test-tmp"
    parent_dir.mkdir(parents=True, exist_ok=True)
    directory = create_kerberos_temp_dir(parent_dir)
    try:
        file_path = directory / "krb5.conf"
        file_path.write_text("test", encoding="utf-8")
        assert file_path.read_text(encoding="utf-8") == "test"
    finally:
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
