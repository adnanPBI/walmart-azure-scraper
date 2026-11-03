"""Read-only Walmart #72 Azure guest/Key Vault verification.

Only Azure CLI account show and EXACTLY two known Key Vault Get Secret
operations are allowed. The returned secret values are never printed,
persisted, logged, or supplied to a provider or Azure job.

Azure guest sign-in is an attended prerequisite, not performed here.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from typing import Callable

TENANT = "b6d4bd45-c947-4f69-9949-7e688a70561e"
ACCOUNT = "adnanrnd@outlook.com"
VAULT = "shif1021-kv-hfpzua5n"
SECRET_NAMES = ("oxylabs-username", "oxylabs-password")
TIMEOUT = 20


def error_code(stderr: str) -> str:
    """Return only recognized diagnostic codes, NEVER arbitrary CLI text."""
    text = stderr or ""
    match = re.search(r"AADSTS[0-9]{5,8}", text, flags=re.I)
    if match:
        return match.group().upper()
    for code in ("ForbiddenByRbac", "SecretNotFound", "AuthorizationFailed",
                 "Forbidden", "ResourceNotFound", "CredentialUnavailable",
                 "ExpiredAuthenticationToken"):
        if re.search(r"\b" + re.escape(code) + r"\b", text, flags=re.I):
            return code.upper()
    if "az login" in text.lower() or "login required" in text.lower():
        return "LOGIN_REQUIRED"
    return "REDACTED_CLI_ERROR"


def _run(runner: Callable, argv: list[str]):
    return runner(argv, capture_output=True, text=True, timeout=TIMEOUT, check=False)


def _expected_user(user: str) -> bool:
    value=(user or "").casefold()
    return value == ACCOUNT or value.split("#ext#")[0] == ACCOUNT.replace("@", "_")


def verify(az_exe: str | None = None, runner: Callable = subprocess.run) -> dict:
    """Never call Key Vault until the expected tenant AND user are confirmed."""
    report = {
        "kind": "WALMART72_READ_ONLY_NO_SECRET_VALUES",
        "tenant_checked": TENANT,
        "vault_checked": VAULT,
        "auth_status": "NOT_CHECKED",
        "secrets": {name: "NOT_ATTEMPTED" for name in SECRET_NAMES},
        "paid_requests": 0,
        "azure_resources_created": 0,
        "scheduled_jobs_enabled": False,
    }
    executable = az_exe or shutil.which("az")
    if not executable:
        report["auth_status"] = "AZ_CLI_MISSING"
        return report
    try:
        response = _run(runner, [executable, "account", "show",
            "--query", "{tenant:tenantId,user:user.name}",
            "--output", "json", "--only-show-errors"])
    except subprocess.TimeoutExpired:
        report["auth_status"] = "ACCOUNT_QUERY_TIMEOUT"
        return report
    except OSError:
        report["auth_status"] = "ACCOUNT_QUERY_OS_ERROR"
        return report
    if response.returncode != 0:
        report["auth_status"] = error_code(response.stderr)
        return report
    try:
        context = json.loads(response.stdout)
    except (ValueError,TypeError):
        report["auth_status"] = "INVALID_ACCOUNT_METADATA"
        return report
    if not isinstance(context, dict) or context.get("tenant") != TENANT:
        report["auth_status"] = "WRONG_TENANT"
        return report
    if not _expected_user(str(context.get("user", ""))):
        report["auth_status"] = "UNEXPECTED_SIGNED_IN_USER"
        return report
    report["auth_status"] = "EXPECTED_USER_AND_TENANT_CONFIRMED"
    for name in SECRET_NAMES:
        try:
            # --output none never prints the response containing the value.
            # This is a Get Secret by exact name, NEVER a list operation.
            response = _run(runner, [executable, "keyvault", "secret", "show",
                "--vault-name", VAULT, "--name", name,
                "--query", "id", "--output", "none", "--only-show-errors"])
            report["secrets"][name] = (
                "GET_SUCCEEDED_VALUE_NOT_DISPLAYED" if response.returncode == 0
                else "GET_FAILED_" + error_code(response.stderr)
            )
        except subprocess.TimeoutExpired:
            report["secrets"][name] = "GET_TIMEOUT"
        except OSError:
            report["secrets"][name] = "GET_OS_ERROR"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Redacted, read-only Azure Key Vault verification")
    parser.add_argument("--az-exe", default=None, help="Optional absolute portable az.cmd path")
    args = parser.parse_args(argv)
    result = verify(args.az_exe)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if (result["auth_status"] == "EXPECTED_USER_AND_TENANT_CONFIRMED"
        and all(value == "GET_SUCCEEDED_VALUE_NOT_DISPLAYED"
                for value in result["secrets"].values())) else 2


if __name__ == "__main__":
    raise SystemExit(main())
