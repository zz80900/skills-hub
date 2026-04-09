from __future__ import annotations

import base64
import logging
import math
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.core.config import get_settings


logger = logging.getLogger(__name__)


class ActiveDirectoryError(Exception):
    """Base class for Active Directory integration failures."""


class ActiveDirectoryUnavailableError(ActiveDirectoryError):
    """Raised when AD integration is misconfigured or temporarily unavailable."""


class ActiveDirectoryInvalidCredentialsError(ActiveDirectoryError):
    """Raised when Kerberos rejects the user credentials."""


class ActiveDirectoryLookupError(ActiveDirectoryError):
    """Raised when Kerberos succeeds but LDAP cannot resolve the user."""


@dataclass(slots=True, frozen=True)
class ActiveDirectoryIdentity:
    username: str
    principal: str
    display_name: str
    name_source: str
    external_principal: str
    distinguished_name: str
    attributes: dict[str, list[str]]


def authenticate_active_directory_user(username: str, password: str) -> ActiveDirectoryIdentity:
    authenticator = ActiveDirectoryAuthenticator(get_settings())
    return authenticator.authenticate(username, password)


class ActiveDirectoryAuthenticator:
    def __init__(self, settings):
        self._settings = settings

    def authenticate(self, username: str, password: str) -> ActiveDirectoryIdentity:
        self._ensure_enabled()
        if not password:
            raise ActiveDirectoryInvalidCredentialsError("missing password")

        account_name = normalize_account_name(username)
        principal = normalize_principal(username, self._settings.ad_realm)
        credential_env: dict[str, str] | None = None

        try:
            credential_env = self._run_kinit(principal, password)
            return self._lookup_user(account_name, principal)
        finally:
            if credential_env is not None:
                self._run_kdestroy(credential_env)

    def _ensure_enabled(self) -> None:
        required_values = {
            "AD_REALM": self._settings.ad_realm,
            "AD_KDC": self._settings.ad_kdc,
            "AD_LDAP_URL": self._settings.ad_ldap_url,
            "AD_BASE_DN": self._settings.ad_base_dn,
            "AD_LDAP_BIND_USERNAME": self._settings.ad_ldap_bind_username,
            "AD_LDAP_BIND_PASSWORD": self._settings.ad_ldap_bind_password,
        }
        if not self._settings.ad_enabled:
            raise ActiveDirectoryUnavailableError("AD authentication is disabled")
        missing_names = [name for name, value in required_values.items() if not (value or "").strip()]
        if missing_names:
            raise ActiveDirectoryUnavailableError(f"missing AD configuration: {', '.join(missing_names)}")

    def _run_kinit(self, principal: str, password: str) -> dict[str, str]:
        command = build_command(self._settings.ad_kinit_command)
        executable = resolve_executable(command[0])
        tempdir = str(create_kerberos_temp_dir())
        krb5_conf_path = self._settings.ad_kdc and write_krb5_conf(
            Path(tempdir),
            self._settings.ad_realm,
            self._settings.ad_kdc,
        )
        env = {
            **os.environ,
            "KRB5CCNAME": f"FILE:{Path(tempdir) / 'krb5cc'}",
            "SSC_SKILLS_KRB5_TMPDIR": tempdir,
        }
        if krb5_conf_path is not None:
            env["KRB5_CONFIG"] = str(krb5_conf_path)

        result = subprocess.run(
            [executable, *command[1:], principal],
            input=f"{password}\n",
            capture_output=True,
            text=True,
            timeout=self._settings.ad_kerberos_timeout_seconds,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise classify_kerberos_failure(result.stdout, result.stderr)
        return env

    def _run_kdestroy(self, env: dict[str, str]) -> None:
        try:
            command = build_command(self._settings.ad_kdestroy_command)
            executable = resolve_executable(command[0], required=False)
            if executable is None:
                return
            subprocess.run(
                [executable, *command[1:]],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return
        finally:
            tempdir = env.get("SSC_SKILLS_KRB5_TMPDIR")
            if tempdir:
                shutil.rmtree(tempdir, ignore_errors=True)

    def _lookup_user(self, account_name: str, principal: str) -> ActiveDirectoryIdentity:
        try:
            import ldap3
            from ldap3.utils.conv import escape_filter_chars
        except ImportError as exc:
            raise ActiveDirectoryUnavailableError("missing python dependency: ldap3") from exc

        bind_password = self._settings.ad_ldap_bind_password
        ldap_timeout_seconds = normalize_ldap_timeout_seconds(self._settings.ad_ldap_timeout_seconds)
        bind_candidates = build_ldap_service_bind_principals(
            ldap_bind_username=self._settings.ad_ldap_bind_username,
            ldap_bind_principal=self._settings.ad_ldap_bind_principal,
            realm=self._settings.ad_realm,
            netbios_domain=self._settings.ad_netbios_domain,
        )

        last_error: Exception | None = None
        connection = None
        for server_kwargs in build_ldap_server_kwargs_candidates(self._settings.ad_ldap_url):
            server = ldap3.Server(
                get_info=ldap3.NONE,
                connect_timeout=ldap_timeout_seconds,
                **server_kwargs,
            )
            for bind_name in bind_candidates:
                try:
                    connection = ldap3.Connection(
                        server,
                        user=bind_name,
                        password=bind_password,
                        authentication=ldap3.SIMPLE,
                        auto_bind=True,
                        receive_timeout=ldap_timeout_seconds,
                        read_only=True,
                    )
                    break
                except Exception as exc:  # pragma: no cover - real LDAP errors depend on environment
                    last_error = exc
                    logger.warning(
                        "LDAP bind failed for server=%s bind=%s: %s",
                        describe_ldap_server_kwargs(server_kwargs),
                        bind_name,
                        exc,
                    )
            if connection is not None:
                break

        if connection is None:
            raise classify_ldap_failure(last_error)

        try:
            search_filter = (
                "(&(objectCategory=person)(objectClass=user)"
                f"(|(userPrincipalName={escape_filter_chars(principal)})"
                f"(sAMAccountName={escape_filter_chars(account_name)})))"
            )
            last_lookup_error: Exception | None = None
            for search_base in build_search_bases(
                base_dn=self._settings.ad_base_dn,
                realm=self._settings.ad_realm,
                domain_root_dn=self._settings.ad_domain_root_dn,
            ):
                try:
                    connection.search(
                        search_base=search_base,
                        search_filter=search_filter,
                        search_scope=ldap3.SUBTREE,
                        attributes=ldap3.ALL_ATTRIBUTES,
                        size_limit=2,
                    )
                except Exception as exc:  # pragma: no cover - real LDAP errors depend on environment
                    last_lookup_error = exc
                    logger.warning(
                        "LDAP search failed for base=%s principal=%s: %s",
                        search_base,
                        principal,
                        exc,
                    )
                    continue
                if connection.entries:
                    entry = connection.entries[0]
                    attributes = collect_attributes(entry)
                    display_name, name_source = resolve_ldap_name(attributes)
                    principal_from_ldap = first_attribute(attributes, "userPrincipalName") or principal
                    resolved_username = normalize_account_name(
                        first_attribute(attributes, "sAMAccountName") or account_name
                    )
                    return ActiveDirectoryIdentity(
                        username=resolved_username,
                        principal=principal,
                        display_name=display_name,
                        name_source=name_source,
                        external_principal=principal_from_ldap,
                        distinguished_name=first_attribute(attributes, "distinguishedName") or "",
                        attributes=attributes,
                    )

            if last_lookup_error is not None:
                raise classify_ldap_failure(last_lookup_error)
            raise ActiveDirectoryLookupError("ldap user not found")
        finally:
            try:
                connection.unbind()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def normalize_account_name(username: str) -> str:
    value = (username or "").strip()
    if "\\" in value:
        value = value.rsplit("\\", 1)[-1]
    if "@" in value:
        value = value.split("@", 1)[0]
    return value.lower()


def normalize_principal(username: str, realm: str) -> str:
    account_name = normalize_account_name(username)
    return f"{account_name}@{(realm or '').strip().upper()}"


def build_ldap_service_bind_principals(
    *,
    ldap_bind_username: str,
    ldap_bind_principal: str,
    realm: str,
    netbios_domain: str,
) -> list[str]:
    candidates: list[str] = []
    if (ldap_bind_principal or "").strip():
        candidates.append(ldap_bind_principal.strip())

    username = (ldap_bind_username or "").strip()
    if username:
        candidates.append(f"{username}@{(realm or '').strip().upper()}")
        domain = (netbios_domain or "").strip().upper() or (realm.split(".", 1)[0].strip().upper() if realm else "")
        if domain:
            candidates.append(f"{domain}\\{username}")
    return dedupe_strings(candidates)


def build_search_bases(*, base_dn: str, realm: str, domain_root_dn: str) -> list[str]:
    normalized_base_dn = normalize_base_dn(base_dn, realm)
    fallback_root = (domain_root_dn or "").strip() or build_domain_root_dn(realm)
    return dedupe_strings([normalized_base_dn, fallback_root])


def build_ldap_server_kwargs_candidates(ldap_url: str) -> list[dict[str, Any]]:
    host, port, use_ssl = parse_ldap_server_url(ldap_url)
    candidates = [
        {"host": host, "port": port, "use_ssl": use_ssl},
    ]

    raw_value = (ldap_url or "").strip()
    if "://" in raw_value:
        candidates.append({"host": raw_value})
    return dedupe_ldap_server_kwargs(candidates)


def normalize_ldap_timeout_seconds(timeout_seconds: float | int) -> int:
    value = float(timeout_seconds)
    if value <= 0:
        raise ActiveDirectoryUnavailableError(f"invalid ldap timeout: {timeout_seconds}")
    return max(1, math.ceil(value))


def parse_ldap_server_url(ldap_url: str) -> tuple[str, int | None, bool]:
    value = (ldap_url or "").strip()
    if not value:
        raise ActiveDirectoryUnavailableError("missing ldap url")

    if "://" not in value:
        host = value
        port: int | None = None
        if value.count(":") == 1:
            host_candidate, port_candidate = value.rsplit(":", 1)
            if port_candidate.isdigit():
                host = host_candidate
                port = int(port_candidate)
        return host.strip(), port, False

    parsed = urlparse(value)
    if parsed.scheme not in {"ldap", "ldaps"} or not parsed.hostname:
        raise ActiveDirectoryUnavailableError(f"invalid ldap url: {value}")
    return parsed.hostname, parsed.port or (636 if parsed.scheme == "ldaps" else 389), parsed.scheme == "ldaps"


def normalize_base_dn(base_dn: str, realm: str) -> str:
    value = (base_dn or "").strip()
    if "|" not in value:
        return value
    ou_parts = [part.strip() for part in value.split("|") if part.strip()]
    domain_root = build_domain_root_dn(realm)
    return ",".join([*reversed(ou_parts), domain_root])


def build_domain_root_dn(realm: str) -> str:
    segments = [segment.strip().lower() for segment in (realm or "").split(".") if segment.strip()]
    if not segments:
        return ""
    return ",".join(f"DC={segment}" for segment in segments)


def resolve_ldap_name(attributes: dict[str, list[str]]) -> tuple[str, str]:
    surname = first_attribute(attributes, "sn")
    given_name = first_attribute(attributes, "givenName")
    if surname and given_name:
        return f"{surname}{given_name}", "sn+givenName"

    for attribute_name, source in (
        ("displayName", "displayName"),
        ("cn", "cn"),
        ("name", "name"),
    ):
        value = first_attribute(attributes, attribute_name)
        if value:
            return value, source
    return first_attribute(attributes, "sAMAccountName") or "", "sAMAccountName"


def collect_attributes(entry: Any) -> dict[str, list[str]]:
    attributes: dict[str, list[str]] = {}
    for attribute_name in sorted(getattr(entry, "entry_attributes", []), key=str.lower):
        raw_value = getattr(entry[attribute_name], "value", None)
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        normalized_values = [normalize_ldap_value(item) for item in values if item not in (None, "")]
        if normalized_values:
            attributes[attribute_name] = normalized_values
    return attributes


def normalize_ldap_value(value: Any) -> str:
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value)


def first_attribute(attributes: dict[str, list[str]], attribute_name: str) -> str:
    for key, values in attributes.items():
        if key.lower() == attribute_name.lower() and values:
            return values[0]
    return ""


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        lookup_key = normalized.lower()
        if lookup_key in seen:
            continue
        seen.add(lookup_key)
        result.append(normalized)
    return result


def dedupe_ldap_server_kwargs(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for value in values:
        normalized = {key: value[key] for key in sorted(value)}
        lookup_key = tuple((key, str(normalized[key])) for key in normalized)
        if lookup_key in seen:
            continue
        seen.add(lookup_key)
        result.append(normalized)
    return result


def describe_ldap_server_kwargs(server_kwargs: dict[str, Any]) -> str:
    return ",".join(f"{key}={server_kwargs[key]}" for key in sorted(server_kwargs))


def create_kerberos_temp_dir(parent_dir: Path | None = None) -> Path:
    root_dir = parent_dir or Path(tempfile.gettempdir())
    while True:
        path = root_dir / f"nexgo-skills-krb5-{secrets.token_hex(8)}"
        try:
            path.mkdir(parents=True, exist_ok=False)
            return path
        except FileExistsError:  # pragma: no cover - collision is unlikely
            continue


def write_krb5_conf(directory: Path, realm: str, kdc: str) -> Path:
    path = directory / "krb5.conf"
    content = (
        "[libdefaults]\n"
        f"  default_realm = {(realm or '').strip().upper()}\n"
        "  dns_lookup_kdc = false\n"
        "  dns_lookup_realm = false\n"
        "\n"
        "[realms]\n"
        f"  {(realm or '').strip().upper()} = {{\n"
        f"    kdc = {(kdc or '').strip()}\n"
        "  }\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def build_command(command: str) -> list[str]:
    parts = shlex.split(command or "", posix=os.name != "nt")
    if not parts:
        raise ActiveDirectoryUnavailableError("missing kerberos command")
    return parts


def resolve_executable(executable: str, *, required: bool = True) -> str | None:
    if Path(executable).is_file():
        return executable
    resolved = shutil.which(executable)
    if resolved is not None:
        return resolved
    if required:
        raise ActiveDirectoryUnavailableError(f"kerberos command not found: {executable}")
    return None


def classify_kerberos_failure(stdout: str, stderr: str) -> ActiveDirectoryError:
    detail = " ".join(part.strip() for part in [stdout, stderr] if part.strip()).lower()
    if any(fragment in detail for fragment in ["pre-authentication", "password incorrect", "integrity check"]):
        return ActiveDirectoryInvalidCredentialsError(detail)
    if "client not found" in detail:
        return ActiveDirectoryInvalidCredentialsError(detail)
    if "clock skew" in detail:
        return ActiveDirectoryUnavailableError(detail)
    if any(fragment in detail for fragment in ["cannot contact any kdc", "connection refused", "no route to host"]):
        return ActiveDirectoryUnavailableError(detail)
    if any(fragment in detail for fragment in ["cannot locate kdc", "cannot find kdc", "realm not local to kdc"]):
        return ActiveDirectoryUnavailableError(detail)
    return ActiveDirectoryUnavailableError(detail or "kerberos authentication failed")


def classify_ldap_failure(error: Exception | None) -> ActiveDirectoryError:
    detail = str(error or "").lower()
    if "invalid credentials" in detail:
        return ActiveDirectoryUnavailableError(detail)
    if any(fragment in detail for fragment in ["connection refused", "socket", "timed out", "connect error"]):
        return ActiveDirectoryUnavailableError(detail)
    if "no such object" in detail:
        return ActiveDirectoryUnavailableError(detail)
    if "size limit exceeded" in detail:
        return ActiveDirectoryUnavailableError(detail)
    return ActiveDirectoryUnavailableError(detail or "ldap lookup failed")
