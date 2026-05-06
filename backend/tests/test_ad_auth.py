from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ad_auth import (
    ActiveDirectoryUnavailableError,
    build_ldap_server_kwargs_candidates,
    create_kerberos_temp_dir,
    normalize_ldap_timeout_seconds,
    parse_organization_hierarchy,
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


def test_normalize_ldap_timeout_seconds_rounds_up_to_int():
    assert normalize_ldap_timeout_seconds(15.0) == 15
    assert normalize_ldap_timeout_seconds(15.1) == 16


def test_normalize_ldap_timeout_seconds_rejects_non_positive():
    try:
        normalize_ldap_timeout_seconds(0)
    except ActiveDirectoryUnavailableError as exc:
        assert str(exc) == "invalid ldap timeout: 0"
    else:
        raise AssertionError("expected ActiveDirectoryUnavailableError")


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


def test_parse_organization_hierarchy_removes_shared_root_and_keeps_four_levels():
    result = parse_organization_hierarchy(
        "CN=谢金城,OU=系统方案部,OU=公共技术中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
    )
    assert result.levels == ("支付硬件事业群", "技术中心", "公共技术中心", "系统方案部")
    assert result.path == "支付硬件事业群 / 技术中心 / 公共技术中心 / 系统方案部"
    assert result.depth == 4


def test_parse_organization_hierarchy_trims_shared_root_before_limiting_levels():
    result = parse_organization_hierarchy(
        "CN=alice,OU=应用一组,OU=平台研发部,OU=研发中心,OU=技术中心,OU=支付硬件事业群,OU=新国都集团,DC=xgd,DC=com"
    )
    assert result.levels == ("支付硬件事业群", "技术中心", "研发中心", "平台研发部")
    assert result.path == "支付硬件事业群 / 技术中心 / 研发中心 / 平台研发部"
    assert result.depth == 4


def test_parse_organization_hierarchy_keeps_partial_levels():
    result = parse_organization_hierarchy("CN=alice,OU=平台研发部,OU=研发中心,OU=新国都集团,DC=xgd,DC=com")
    assert result.levels == ("研发中心", "平台研发部")
    assert result.path == "研发中心 / 平台研发部"
    assert result.depth == 2


def test_parse_organization_hierarchy_handles_empty_dn():
    result = parse_organization_hierarchy("")
    assert result.levels == tuple()
    assert result.path == ""
    assert result.depth == 0
