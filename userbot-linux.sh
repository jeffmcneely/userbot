#!/usr/bin/env bash
set -euo pipefail

USERBOT_URL="${USERBOT_URL:-${USERBOT:-}}"
SEARCHROOT="${SEARCHROOT:-}"
NUMBER_OF_DAYS="${NUMBER_OF_DAYS:--3}"
AUTH_HEADER="${AUTH_HEADER:-}"
LDAP_URI="${LDAP_URI:-}"
LDAP_BIND_DN="${LDAP_BIND_DN:-}"
LDAP_BIND_PASSWORD="${LDAP_BIND_PASSWORD:-}"
LDAP_BIND_PASSWORD_FILE="${LDAP_BIND_PASSWORD_FILE:-}"

LDAPSEARCH_BIN="${LDAPSEARCH_BIN:-ldapsearch}"
CURL_BIN="${CURL_BIN:-curl}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

SEARCHROOT="${SEARCHROOT#LDAP://}"
TEMP_PASSWORD_FILE=""

cleanup() {
    if [[ -n "$TEMP_PASSWORD_FILE" && -f "$TEMP_PASSWORD_FILE" ]]; then
        rm -f "$TEMP_PASSWORD_FILE"
    fi
}

trap cleanup EXIT

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

require_value() {
    local name="$1"
    local value="${!name}"

    if [[ -z "$value" ]]; then
        echo "Set $name before running this script." >&2
        exit 1
    fi
}

prepare_password_file() {
    if [[ -z "$LDAP_BIND_DN" ]]; then
        return
    fi

    if [[ -n "$LDAP_BIND_PASSWORD_FILE" ]]; then
        if [[ ! -f "$LDAP_BIND_PASSWORD_FILE" ]]; then
            echo "LDAP_BIND_PASSWORD_FILE does not exist: $LDAP_BIND_PASSWORD_FILE" >&2
            exit 1
        fi
        return
    fi

    if [[ -z "$LDAP_BIND_PASSWORD" ]]; then
        echo "Set LDAP_BIND_PASSWORD_FILE or LDAP_BIND_PASSWORD when LDAP_BIND_DN is configured." >&2
        exit 1
    fi

    TEMP_PASSWORD_FILE="$(mktemp)"
    chmod 600 "$TEMP_PASSWORD_FILE"
    printf '%s' "$LDAP_BIND_PASSWORD" > "$TEMP_PASSWORD_FILE"
    LDAP_BIND_PASSWORD_FILE="$TEMP_PASSWORD_FILE"
}

build_timestamp() {
    date -u -d "${NUMBER_OF_DAYS} days" '+%Y%m%d%H%M%S.0Z'
}

run_ldapsearch() {
    local filter="$1"
    shift

    local -a cmd=(
        "$LDAPSEARCH_BIN"
        -LLL
        -o
        ldif-wrap=no
        -o
        nettimeout=15
        -x
        -H
        "$LDAP_URI"
        -b
        "$SEARCHROOT"
        -E
        pr=1000/noprompt
    )

    if [[ -n "$LDAP_BIND_DN" ]]; then
        cmd+=(
            -D
            "$LDAP_BIND_DN"
            -y
            "$LDAP_BIND_PASSWORD_FILE"
        )
    fi

    cmd+=("$filter" "$@")
    "${cmd[@]}"
}

emit_request_bodies() {
    local event_name="$1"

    "$PYTHON_BIN" -c '
import base64
import json
import sys

event_name = sys.argv[1]
wanted = {"samaccountname", "name", "title", "manager", "whencreated"}
current = {}

def decode_value(raw_line: str):
    if ":: " in raw_line:
        key, value = raw_line.split(":: ", 1)
        return key.lower(), base64.b64decode(value).decode("utf-8")
    if ": " in raw_line:
        key, value = raw_line.split(": ", 1)
        return key.lower(), value
    return None, None

def flush() -> None:
    sam = current.get("samaccountname", "")
    if not sam:
        return

    message = {
        "event": event_name,
        "sam": sam,
        "name": current.get("name", ""),
        "title": current.get("title", ""),
        "manager": current.get("manager", ""),
    }
    if event_name == "disable":
        message["created"] = current.get("whencreated", "")

    encoded = base64.b64encode(
        json.dumps(message, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    print(json.dumps({"data": encoded}, separators=(",", ":")))

for raw_line in sys.stdin:
    line = raw_line.rstrip("\n")
    if not line:
        flush()
        current.clear()
        continue

    key, value = decode_value(line)
    if key in wanted and key not in current:
        current[key] = value

flush()
' "$event_name"
}

post_search_results() {
    local event_name="$1"
    local filter="$2"
    shift 2

    while IFS= read -r request_body; do
        if [[ -z "$request_body" ]]; then
            continue
        fi

        "$CURL_BIN" \
            --silent \
            --show-error \
            --fail \
            --request POST \
            --header 'Content-Type: application/json; charset=utf-8' \
            --header "X-Auth-Header: $AUTH_HEADER" \
            --data "$request_body" \
            "$USERBOT_URL" >/dev/null
    done < <(run_ldapsearch "$filter" "$@" | emit_request_bodies "$event_name")
}

main() {
    require_command "$LDAPSEARCH_BIN"
    require_command "$CURL_BIN"
    require_command "$PYTHON_BIN"
    require_command mktemp
    require_command date

    require_value USERBOT_URL
    require_value SEARCHROOT
    require_value AUTH_HEADER
    require_value LDAP_URI

    prepare_password_file

    local then
    then="$(build_timestamp)"

    post_search_results \
        new \
        "(&(objectClass=user)(whenCreated>=$then))" \
        samAccountName name title manager

    post_search_results \
        disable \
        "(&(objectClass=user)(userAccountControl:1.2.840.113556.1.4.803:=2)(whenChanged>=$then))" \
        samAccountName name title manager whenCreated
}

main "$@"