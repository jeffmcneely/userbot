#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: requests. Install with `python3 -m pip install requests ldap3`."
    ) from exc

try:
    from ldap3 import ANONYMOUS, NTLM, SIMPLE, SUBTREE, Connection, Server
    from ldap3.core.exceptions import LDAPException
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: ldap3. Install with `python3 -m pip install requests ldap3`."
    ) from exc


REQUEST_TIMEOUT_SECONDS = 15
PAGE_SIZE = 1000


@dataclass(frozen=True)
class Config:
    userbot_url: str
    searchroot: str
    number_of_days: int
    auth_header: str
    ldap_uri: str
    ldap_bind_dn: str
    ldap_bind_password: str
    ldap_auth_type: str


def required_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value

    joined_names = ", ".join(names)
    raise ValueError(f"Set one of these environment variables before running: {joined_names}")


def load_password(bind_dn: str) -> str:
    password_file = os.getenv("LDAP_BIND_PASSWORD_FILE", "").strip()
    password = os.getenv("LDAP_BIND_PASSWORD", "")

    if not bind_dn:
        if password_file or password:
            raise ValueError(
                "Set LDAP_BIND_DN when using LDAP_BIND_PASSWORD_FILE or LDAP_BIND_PASSWORD."
            )
        return ""

    if password_file:
        password_path = Path(password_file).expanduser()
        try:
            return password_path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise ValueError(
                f"Unable to read LDAP_BIND_PASSWORD_FILE {password_path}: {exc}"
            ) from exc

    if password:
        return password

    raise ValueError(
        "Set LDAP_BIND_PASSWORD_FILE or LDAP_BIND_PASSWORD when LDAP_BIND_DN is configured."
    )


def load_config() -> Config:
    searchroot = required_env("SEARCHROOT")
    number_of_days = int(os.getenv("NUMBER_OF_DAYS", "-3"))
    ldap_bind_dn = os.getenv("LDAP_BIND_DN", "").strip()
    ldap_auth_type = os.getenv("LDAP_AUTH_TYPE", "SIMPLE").strip().upper() or "SIMPLE"

    if ldap_auth_type not in {"SIMPLE", "NTLM"}:
        raise ValueError("LDAP_AUTH_TYPE must be SIMPLE or NTLM.")

    return Config(
        userbot_url=required_env("USERBOT_URL", "USERBOT"),
        searchroot=searchroot.removeprefix("LDAP://"),
        number_of_days=number_of_days,
        auth_header=required_env("AUTH_HEADER"),
        ldap_uri=required_env("LDAP_URI"),
        ldap_bind_dn=ldap_bind_dn,
        ldap_bind_password=load_password(ldap_bind_dn),
        ldap_auth_type=ldap_auth_type,
    )


def build_timestamp(number_of_days: int) -> str:
    then = datetime.now(timezone.utc) + timedelta(days=number_of_days)
    return then.strftime("%Y%m%d%H%M%S.0Z")


def parse_ldap_uri(ldap_uri: str) -> tuple[str, int, bool]:
    parsed = urlparse(ldap_uri)

    if parsed.scheme not in {"ldap", "ldaps"}:
        raise ValueError("LDAP_URI must start with ldap:// or ldaps://")

    if not parsed.hostname:
        raise ValueError("LDAP_URI must include a hostname")

    use_ssl = parsed.scheme == "ldaps"
    default_port = 636 if use_ssl else 389
    return parsed.hostname, parsed.port or default_port, use_ssl


def create_connection(config: Config) -> Connection:
    host, port, use_ssl = parse_ldap_uri(config.ldap_uri)
    server = Server(
        host,
        port=port,
        use_ssl=use_ssl,
        connect_timeout=REQUEST_TIMEOUT_SECONDS,
    )

    connection_args: dict[str, Any] = {
        "server": server,
        "auto_bind": True,
        "raise_exceptions": True,
        "receive_timeout": REQUEST_TIMEOUT_SECONDS,
        "read_only": True,
    }

    if config.ldap_bind_dn:
        authentication = NTLM if config.ldap_auth_type == "NTLM" else SIMPLE
        connection_args.update(
            {
                "user": config.ldap_bind_dn,
                "password": config.ldap_bind_password,
                "authentication": authentication,
            }
        )
    else:
        connection_args["authentication"] = ANONYMOUS

    return Connection(**connection_args)


def first_attribute(raw_attributes: dict[str, list[bytes]], attribute_name: str) -> str:
    expected_name = attribute_name.lower()

    for name, values in raw_attributes.items():
        if name.lower() != expected_name or not values:
            continue

        value = values[0]
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    return ""


def iter_event_payloads(
    connection: Connection,
    searchroot: str,
    event_name: str,
    search_filter: str,
    include_created: bool,
):
    attributes = ["samAccountName", "name", "title", "manager"]
    if include_created:
        attributes.append("whenCreated")

    results = connection.extend.standard.paged_search(
        search_base=searchroot,
        search_filter=search_filter,
        search_scope=SUBTREE,
        attributes=attributes,
        paged_size=PAGE_SIZE,
        generator=True,
    )

    for result in results:
        if result.get("type") != "searchResEntry":
            continue

        raw_attributes = result.get("raw_attributes", {})
        sam = first_attribute(raw_attributes, "samAccountName")
        if not sam:
            continue

        payload = {
            "event": event_name,
            "sam": sam,
            "name": first_attribute(raw_attributes, "name"),
            "title": first_attribute(raw_attributes, "title"),
            "manager": first_attribute(raw_attributes, "manager"),
        }

        if include_created:
            payload["created"] = first_attribute(raw_attributes, "whenCreated")

        yield payload


def post_payload(session: requests.Session, config: Config, payload: dict[str, str]) -> None:
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    body = {"data": encoded}

    response = session.post(
        config.userbot_url,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Auth-Header": config.auth_header,
        },
        json=body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def main() -> int:
    try:
        config = load_config()
        then = build_timestamp(config.number_of_days)
        connection = create_connection(config)
    except (ValueError, LDAPException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    new_user_filter = f"(&(objectClass=user)(whenCreated>={then}))"
    disabled_user_filter = (
        f"(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=2)"
        f"(whenChanged>={then}))"
    )

    try:
        with requests.Session() as session:
            for payload in iter_event_payloads(
                connection,
                config.searchroot,
                "new",
                new_user_filter,
                include_created=False,
            ):
                post_payload(session, config, payload)

            for payload in iter_event_payloads(
                connection,
                config.searchroot,
                "disable",
                disabled_user_filter,
                include_created=True,
            ):
                post_payload(session, config, payload)
    except (LDAPException, requests.RequestException) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.unbind()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())