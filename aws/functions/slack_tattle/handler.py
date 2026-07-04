import json
import boto3
from botocore.exceptions import ClientError
import requests
import base64
from typing import Any, Literal, Optional
import os
import time


json_headers = {"Content-type": "application/json"}


def get_header_value(
    headers: Optional[dict[str, str]], header_name: str
) -> Optional[str]:
    if not headers:
        return None

    expected_name = header_name.lower()
    for key, value in headers.items():
        if key.lower() == expected_name:
            return value

    return None

def get_org_prefix(boto_session):
    """Load organization prefix from Systems Manager Parameter Store"""
    ssm_client = boto_session.client("ssm")
    prefix = os.environ.get("PREFIX")
    param_name = f"/{prefix}/ou_root"
    
    try:
        response = ssm_client.get_parameter(Name=param_name)
        return response["Parameter"]["Value"]
    except ClientError as e:
        raise ValueError(f"Failed to retrieve org_prefix from SSM Parameter Store: {e}")


def get_slack_hook(boto_session):
    """Load Slack webhook URL from Secrets Manager"""
    secrets_client = boto_session.client("secretsmanager")
    prefix = os.environ.get("PREFIX")
    secret_name = f"{prefix}/slack_hook"
    
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]
    except ClientError as e:
        raise ValueError(f"Failed to retrieve Slack hook from Secrets Manager: {e}")


def get_auth_header(boto_session):
    """Load authentication header from Secrets Manager"""
    secrets_client = boto_session.client("secretsmanager")
    prefix = os.environ.get("PREFIX")
    secret_name = f"{prefix}/auth_header"
    
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return response["SecretString"]
    except ClientError as e:
        raise ValueError(f"Failed to retrieve auth_header from Secrets Manager: {e}")

response_text = {
    "statusCode": 200,
    "headers": {"Content-Type": "text/plain"},
    "body": "ok",
}

error_response = {
    "statusCode": 401,
    "headers": {"Content-Type": "text/plain"},
    "body": "Unauthorized",
}


def known_event(
    boto_session, event_data: dict[str, Any]
) -> Literal["known", "new", "modify"]:

    dynamodb_table = os.environ.get("DYNAMODB_TABLE")
    if not dynamodb_table:
        raise ValueError("DYNAMODB_TABLE environment variable is not set")

    dynamodb = boto_session.resource("dynamodb")
    table = dynamodb.Table(dynamodb_table)
    eventname = f"{event_data['event']}-{event_data['sam']}"

    ttl = int(time.time()) + (30 * 24 * 60 * 60)
    item = {"eventname": eventname, "data": event_data, "ttl": ttl}

    try:
        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(eventname)",
        )
        return "new"
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code != "ConditionalCheckFailedException":
            raise

    response = table.get_item(Key={"eventname": eventname}, ConsistentRead=True)
    existing_data = response.get("Item", {}).get("data")

    table.put_item(Item=item)

    if existing_data == event_data:
        return "known"

    return "modify"


def lambda_handler(event, context):
    message_text = ""
    js = json.loads(event["body"])
    session = boto3.Session()

    # Verify authentication header
    auth_header = get_header_value(event.get("headers"), "X-Auth-Header")
    expected_auth_header = get_auth_header(session)
    
    if not auth_header or auth_header != expected_auth_header:
        return error_response

    message_data = base64.b64decode(js["data"]).decode("UTF-8")
    md = json.loads(message_data)

    org_prefix = get_org_prefix(session)
    event_status = known_event(session, md)
    if event_status == "known":
        return response_text
    message_manager = md["manager"].replace(org_prefix, "")
    message_manager = message_manager.replace("CN=", "")
    if md["event"] == "new":
        message_text = (
            f"new user {md['name']} - {md['title']} managed by {message_manager}"
        )
    elif md["event"] == "disable":
        message_text = f"disabled user {md['name']} - {md['title']} managed by {message_manager} - created {md['created']}"
    else:
        return
    if event_status == "modify":
        message_text = f"UPDATE: {message_text}"
    out_message = {"text": message_text}
    slack_hook = get_slack_hook(session)
    requests.post(
        slack_hook, headers=json_headers, json=out_message
    )

    return response_text
