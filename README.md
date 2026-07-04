# commands to package up for AWS

lambda_function.py should be in the root of zip and all packages should be there also. In this repo they are stored in `package/` just to not clutter up my view

## SSM Parameters Configuration

The UserBot CloudFormation template requires the following SSM parameters to be configured:

### ou_root (SSM Parameter)

**Name:** `/${Prefix}/ou_root`

**Description:** LDAP Distinguished Name (DN) for the Users organizational unit in Active Directory

**Value Format:**

```bash
,CN=Users,DC=example,DC=com
```

**Type:** String

**Usage:** Used to strip the organizational unit suffix from user DNs when processing AD events.

### slack_hook (SecretsManager Secret)

**Name:** `/${Prefix}/slack_hook`

**Description:** Slack incoming webhook URL for posting notifications

**Value Format:**

```bash
https://hooks.slack.com/services/SECRETS/PATH/HERE
```

**Type:** SecureString (stored in AWS Secrets Manager)

**Usage:** Used to send formatted messages to Slack when new users are created or disabled.

### auth_header (SecretsManager Secret)

**Name:** `${Prefix}/auth_header`

**Description:** Authentication header token for verifying API requests

**Value Format:** Any random UUID or string (generate with `uuidgen` or similar)

```bash
550e8400-e29b-41d4-a716-446655440000
```

**Type:** SecureString (stored in AWS Secrets Manager)

**Usage:** Used to verify that incoming API requests are from authorized sources.

## Setting SSM Parameters

Set the SSM parameters using AWS CLI:

```bash
# Set ou_root parameter
aws ssm put-parameter \
  --name "/userbot/ou_root" \
  --value ",CN=Users,DC=example,DC=com" \
  --type String \
  --overwrite

# Set slack_hook parameter as SecureString
aws ssm put-parameter \
  --name "/userbot/slack_hook" \
  --value "https://hooks.slack.com/services/SECRETS/PATH/HERE" \
  --type SecureString \
  --overwrite

# Generate and set auth_header as SecureString with random UUID
AUTH_HEADER=$(uuidgen)
aws secretsmanager create-secret \
  --name "userbot/auth_header" \
  --secret-string "$AUTH_HEADER"

# Or update existing secret
aws secretsmanager update-secret \
  --secret-id "userbot/auth_header" \
  --secret-string "$AUTH_HEADER"
```

**Note:** Replace the parameter values with your actual OU DN and Slack webhook URL.

## Linux collector script

The repository now includes [userbot-linux.sh](userbot-linux.sh), a Linux version of the PowerShell collector that uses `ldapsearch` and posts the same base64-wrapped JSON payload to the API Gateway.

Required tools:

```bash
# Debian / Ubuntu
sudo apt install ldap-utils curl python3

# RHEL / Rocky / Alma
sudo dnf install openldap-clients curl python3
```

Configure it with environment variables before running:

```bash
export USERBOT_URL="https://example.execute-api.us-east-1.amazonaws.com/default/userbot"
export SEARCHROOT="LDAP://DC=example,DC=com"
export NUMBER_OF_DAYS=-3
export AUTH_HEADER="550e8400-e29b-41d4-a716-446655440000"

export LDAP_URI="ldaps://dc1.example.com:636"
export LDAP_BIND_DN="CN=svc-userbot,OU=Service Accounts,DC=example,DC=com"
export LDAP_BIND_PASSWORD_FILE="$HOME/.config/userbot/ldap.pass"

./userbot-linux.sh
```

Notes:

- `SEARCHROOT` may include the PowerShell-style `LDAP://` prefix; the Linux script strips it automatically before calling `ldapsearch`.
- `LDAP_BIND_PASSWORD_FILE` is preferred so the bind password is not exposed in the process list. If needed, `LDAP_BIND_PASSWORD` is also supported and is copied to a temporary file at runtime.
- The script uses paged LDAP results (`pr=1000/noprompt`) so it can handle larger result sets than a single unpaged `ldapsearch` call.

## Python collector script

The repository also includes [userbot.py](userbot.py), a Python version of the collector that queries LDAP directly and posts the same base64-wrapped JSON payload to the API Gateway.

Install dependencies:

```bash
python3 -m pip install requests ldap3
```

Configure it with environment variables before running:

```bash
export USERBOT_URL="https://example.execute-api.us-east-1.amazonaws.com/default/userbot"
export SEARCHROOT="LDAP://DC=example,DC=com"
export NUMBER_OF_DAYS=-3
export AUTH_HEADER="550e8400-e29b-41d4-a716-446655440000"

export LDAP_URI="ldaps://dc1.example.com:636"
export LDAP_BIND_DN="CN=svc-userbot,OU=Service Accounts,DC=example,DC=com"
export LDAP_BIND_PASSWORD_FILE="$HOME/.config/userbot/ldap.pass"

python3 userbot.py
```

Notes:

- `LDAP_BIND_PASSWORD` can be used instead of `LDAP_BIND_PASSWORD_FILE`.
- `LDAP_AUTH_TYPE` defaults to `SIMPLE`; set it to `NTLM` if your bind account uses `DOMAIN\\username` credentials.
- If `LDAP_BIND_DN` is not set, the script attempts an anonymous bind.

## CloudFormation Deployment

Deploy the template using AWS CLI:

```bash
aws cloudformation create-stack \
  --stack-name userbot \
  --parameters ParameterKey=Prefix,ParameterValue=userbot \
  --capabilities CAPABILITY_NAMED_IAM
```
