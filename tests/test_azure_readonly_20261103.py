"""Offline-only independent Azure login and two exact Key Vault Get Secret checks.

No Azure account, Key Vault, secrets, provider or billable calls in tests.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import json

from scripts import azure_readonly_access as access


def completed(out="", err="", code=0):
    return subprocess.CompletedProcess(args=[],returncode=code,stdout=out,stderr=err)


GOOD_ACCOUNT = json.dumps({
    "tenant": access.TENANT, "user": access.ACCOUNT
})


def test_expected_guest_and_two_independent_reads_never_log_values(capsys):
    calls=[]
    def fake(argv, **kwargs):
        calls.append(argv)
        if argv[1:3]==["account","show"]:
            return completed(GOOD_ACCOUNT)
        return completed('SENSITIVE_BODY_DO_NOT_PRINT')
    status=access.verify("az-mock",fake)
    assert status["auth_status"]=="EXPECTED_USER_AND_TENANT_CONFIRMED"
    assert status["secrets"]=={name:"GET_SUCCEEDED_VALUE_NOT_DISPLAYED"
                              for name in access.SECRET_NAMES}
    assert len(calls)==3
    assert all(x[1:4]==["keyvault","secret","show"] for x in calls[1:])
    assert [x[x.index("--name")+1] for x in calls[1:]] == list(access.SECRET_NAMES)
    assert all("--output" in x and x[x.index("--output")+1]=="none" for x in calls[1:])
    assert all("list" not in x and "login" not in x for x in calls)
    assert all(kwargs=={} for kwargs in [])
    assert "SENSITIVE_BODY_DO_NOT_PRINT" not in json.dumps(status)
    assert "SENSITIVE_BODY_DO_NOT_PRINT" not in capsys.readouterr().out
    assert status["paid_requests"]==0 and status["azure_resources_created"]==0


def test_denied_one_secret_does_not_skip_the_other():
    calls=[]
    def fake(argv, **kwargs):
        calls.append(argv)
        if argv[1:3]==["account","show"]:
            return completed(GOOD_ACCOUNT)
        if argv[argv.index("--name")+1]=="oxylabs-username":
            return completed(err="ERROR: (ForbiddenByRbac) DO-NOT-LOG-ANY-RAW-MSG",code=1)
        return completed("HIDDEN", code=0)
    status=access.verify("az-mock",fake)
    assert status["secrets"]["oxylabs-username"]=="GET_FAILED_FORBIDDENBYRBAC"
    assert status["secrets"]["oxylabs-password"]=="GET_SUCCEEDED_VALUE_NOT_DISPLAYED"
    assert len(calls)==3
    assert "DO-NOT-LOG-ANY-RAW-MSG" not in json.dumps(status)


def test_unsigned_session_never_attempts_secret_reads():
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        return completed(err='ERROR: Please run "az login" first',code=1)
    status=access.verify("az-mock",fake)
    assert status["auth_status"]=="LOGIN_REQUIRED"
    assert len(calls)==1
    assert all(x=="NOT_ATTEMPTED" for x in status["secrets"].values())


def test_wrong_tenant_or_user_never_attempts_secret_reads():
    for context, expected in [
        ({"tenant":"another","user":access.ACCOUNT},"WRONG_TENANT"),
        ({"tenant":access.TENANT,"user":"unknown@example.com"},"UNEXPECTED_SIGNED_IN_USER"),
    ]:
        calls=[]
        def fake(argv,**kwargs):
            calls.append(argv)
            return completed(json.dumps(context))
        status=access.verify("az-mock",fake)
        assert status["auth_status"]==expected
        assert len(calls)==1
        assert set(status["secrets"].values())=={"NOT_ATTEMPTED"}


def test_independent_secret_timeout_and_other_success():
    calls=[]
    def fake(argv,**kwargs):
        calls.append(argv)
        if argv[1:3]==["account","show"]:
            return completed(GOOD_ACCOUNT)
        if argv[argv.index("--name")+1]=="oxylabs-password":
            raise subprocess.TimeoutExpired(argv,20)
        return completed()
    status=access.verify("az-mock",fake)
    assert status["secrets"]["oxylabs-username"]=="GET_SUCCEEDED_VALUE_NOT_DISPLAYED"
    assert status["secrets"]["oxylabs-password"]=="GET_TIMEOUT"


def test_redacted_errors_and_missing_az():
    assert access.error_code("secret-value=bad\nERROR: hidden")=="REDACTED_CLI_ERROR"
    assert access.error_code("AADSTS700016: hidden")=="AADSTS700016"
    status=access.verify("fake", lambda *a, **kw: completed(err="password=HIDDEN",code=1))
    assert "HIDDEN" not in json.dumps(status)
    # No real az command is called; explicit absence is a blocked diagnostic.
    import unittest.mock
    with unittest.mock.patch.object(access.shutil,"which",return_value=None):
        result=access.verify()
    assert result["auth_status"]=="AZ_CLI_MISSING"


def test_script_is_read_only_and_no_vault_listing():
    s=(Path(__file__).resolve().parents[1]/"scripts"/"azure_readonly_access.py").read_text()
    assert 'keyvault", "secret", "show"' in s
    assert 'keyvault", "secret", "list"' not in s
    assert "az login" in s  # login is mentioned only as an error message
    assert "subprocess.run" in s
    assert "execute_billable" not in s
