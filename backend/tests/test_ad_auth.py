from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ad_auth import ActiveDirectoryUnavailableError, parse_ldap_server_url


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
