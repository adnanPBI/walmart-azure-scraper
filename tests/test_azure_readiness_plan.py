"""Offline-only audits of the Azure quote/access/teardown proposal.

No Azure CLI requests, provider calls, credentials, costs or deployed jobs.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
AZ=ROOT/'azure'


def read(path):
    return (ROOT/path).read_text(encoding='utf-8')


def test_azure_script_requires_qualified_source_and_three_approvals():
    s=read('azure/deploy.sh')
    for gate in (
        'AZ_SOURCE_PATH_QUALIFIED',
        'AZ_QUOTE_ACCEPTED',
        'AZ_AUTHORIZE_RESOURCE_CREATION',
        'AZ_AUTHORIZE_SCHEDULED_RUNS',
    ):
        assert gate in s
    assert 'rg-walmart72-' in s
    assert 'purpose=walmart72-temporary' in s
    assert 'az group create' not in s, 'Client must pre-create dedicated group'
    assert 'yaml.safe_load' in s, 'Store configuration equality must ignore comments but not data differences'
    assert 'cmp -s config/stores.yaml' not in s
    assert '--trigger-type Manual' in s or '--trigger-type "Manual"' in s or '--trigger-type' in s and 'Manual' in s
    assert '--replica-retry-limit 0' in s
    assert '--parallelism 1' in s
    assert '--replica-timeout "$AZ_JOB_RUN_TIMEOUT_SECONDS"' in s
    assert '--logs-destination none' in s, 'No unexpected durable log ingestion'
    assert 'CONTAINER_SCOPE=' in s
    assert 'Storage Blob Data Contributor|$CONTAINER_SCOPE' in s
    assert 'Storage Blob Data Contributor|$STORAGE_ID' not in s
    assert '--execute-billable' not in s
    assert '--billing-approved' not in s


def test_manual_dry_run_targets_client_nominated_product_only():
    deploy=read('azure/deploy.sh')
    image=read('Dockerfile.classic')
    for s in (deploy,image):
        assert '10450114' in s
        assert 'https://www.walmart.com/ip/10450114' in s
        assert '--max-requests' in s and '--max-retries' in s
        assert '--max-seconds' in s
        assert '--max-body-bytes' in s
        assert '2000000' in s
        assert '--execute-billable' not in s
    assert 'USER 10001' in image
    assert 'ENTRYPOINT ["walmart-crawl"]' in image


def test_read_only_teardown_script_has_no_delete_operations():
    s=read('azure/teardown_preview.sh')
    assert 'az resource list' in s
    assert 'az group show' in s
    assert "purpose" in s
    assert 'az lock list' in s
    assert 'NO RESOURCES HAVE BEEN DELETED' in s
    for bad in ('\naz group delete ', '\naz resource delete ', '\naz containerapp job start '):
        assert bad not in s


def test_client_plan_explicit_about_scope_estimates_and_remaining_gates():
    s=read('docs/AZURE_LIMITED_ACCESS_AND_MILESTONES_20261101.md')
    for term in (
        '2026', 'November 3', '18:00', 'Asia/Dhaka',
        'Container Apps Jobs Operator','Storage Blob Data Reader',
        'Container Registry Tasks Contributor',
        '5–7 working days','180-second','2,000,000-byte',
        'caller','90-second','NOT', 'teardown',
        'Reader', 'AcrPull','500 genuine', 'source gate',
    ):
        assert term in s,term
    assert 'not an Azure' in s or 'NOT an Azure' in s
    assert 'azure/plan_client_review.sh' in s


@pytest.mark.skipif(shutil.which('bash') is None, reason='Bash is optional on Windows local clients')
def test_print_only_plan_never_requires_az_or_approval(tmp_path):
    # Doesn't install, invoke, discover or even require Azure CLI.
    env=os.environ.copy()
    env.pop('AZ_SOURCE_PATH_QUALIFIED',None)
    env.pop('AZ_AUTHORIZE_RESOURCE_CREATION',None)
    env.pop('AZ_QUOTE_ACCEPTED',None)
    res=subprocess.run(['bash',str(AZ/'plan_client_review.sh')],
        cwd=str(ROOT),env=env,capture_output=True,text=True,timeout=10)
    assert res.returncode==0,res.stderr
    assert '0 AZURE REQUESTS' in res.stdout
    assert 'NOT AUTHORIZED TODAY' in res.stdout
    assert 'az group create' in res.stdout  # printed proposal, NOT executed
    assert 'walmart72-evidence' in res.stdout


@pytest.mark.skipif(shutil.which('bash') is None, reason='Bash is optional on Windows local clients')
def test_unapproved_deployment_fails_before_any_azure_call():
    env=os.environ.copy()
    env.update(AZ_RESOURCE_GROUP='rg-walmart72-test',AZ_REGION='eastus2',
               AZ_STORAGE_ACCOUNT='stwalmart72dummy',
               AZ_ACR_NAME='acrwalmart72dummy')
    for key in ('AZ_SOURCE_PATH_QUALIFIED','AZ_AUTHORIZE_RESOURCE_CREATION','AZ_QUOTE_ACCEPTED'):
        env.pop(key,None)
    res=subprocess.run(['bash',str(AZ/'deploy.sh')],
        cwd=str(ROOT),env=env,capture_output=True,text=True,timeout=10)
    assert res.returncode==4
    assert 'STOP:' in res.stderr
    assert 'client authorization' in res.stderr


def test_example_and_azure_store_configs_match_semantically():
    import yaml
    example=yaml.safe_load(read('config/stores.example.yaml'))
    public=yaml.safe_load(read('config/stores.azure.yaml'))
    assert example==public
    assert read('config/stores.example.yaml')!=read('config/stores.azure.yaml')
