#!/usr/bin/env bash
# PRINT ONLY. This script NEVER invokes az, creates, runs, schedules, bills or deletes.
# Use as a review aid; do not execute the displayed write commands before approval.
set -euo pipefail
RG="${AZ_RESOURCE_GROUP:-rg-walmart72-review-202611}"
REGION="${AZ_REGION:-eastus2}"
ACR="${AZ_ACR_NAME:-acrwalmart72CHANGE}"
STORAGE="${AZ_STORAGE_ACCOUNT:-stwalmart72CHANGE}"
ENV="${AZ_ENV_NAME:-walmart72-diagnostic-env}"
JOB="${AZ_JOB_NAME:-walmart72-classic-job}"
CONTAINER="${AZ_CONTAINER:-walmart72-evidence}"
IDENTITY="${AZ_IDENTITY_NAME:-walmart72-job-identity}"
case "$RG" in rg-walmart72-*) ;; *) echo "STOP: must be an isolated rg-walmart72-* group" >&2; exit 2;; esac
cat <<EOF
WALMART #72 / AZURE PRE-APPROVAL PLAN ONLY — 0 AZURE REQUESTS
Subscription: CLIENT CHOOSES and checks via az account show
Resource group: $RG (client-created, dedicated, never an existing shared group)
Example region: $REGION (client checks availability + quote)
Registry: $ACR (globally unique name must be confirmed)
Storage: $STORAGE (globally unique name must be confirmed)
Container: $CONTAINER; Environment: $ENV; Manual job: $JOB
Identity: $IDENTITY
Build: Dockerfile.classic — ZERO paid Oxylabs calls in container
Job: 0.5 vCPU, 1 GiB, manual trigger only, parallelism 1, retries 0
Replica hard stop: 180 seconds; Classic --max-seconds 90 is a PHASE deadline,
NOT guaranteed caller wall-clock limit if sync receipt filesystem I/O stalls.
EVIDENCE: the initial job outputs a local /tmp dry-run receipt; it does NOT
authenticate #3891 prices or upload verified data to Blob automatically.
Logs: no retained workspace by default; durable logs require a separately
quoted/approved Log Analytics or Azure Monitor integration.
Schedule: OFF.
Teardown: client-operated only after evidence export and resource inventory.

PRECONDITION A: Classic account entitlement confirmed and an authorized,
independently reviewable #3891 PICKUP raw-HTML source path qualified.
PRECONDITION B: Client approves the exact Azure pricing quote, creates and
tags a dedicated group, and authorizes manual deployment (NOT credentials,
paid retailer requests, schedules, or live collection).
PRECONDITION C: Client IAM administrator grants only scoped roles.

READ-ONLY CHECKS (operator executes only after access):
  az account show --query '{subscription:id,tenant:tenantId}' -o json
  az group show -n "$RG" --query '{name:name,location:location,tags:tags}' -o json

CLIENT-OPERATED GROUP PROVISIONING — ONLY AFTER APPROVAL:
  az group create -n "$RG" -l "$REGION" --tags purpose=walmart72-temporary owner=client

EXPLICITLY APPROVED DEPLOYMENT — NOT AUTHORIZED TODAY:
  export AZ_RESOURCE_GROUP="$RG" AZ_REGION="$REGION"
  export AZ_ACR_NAME="$ACR" AZ_STORAGE_ACCOUNT="$STORAGE"
  export AZ_ENV_NAME="$ENV" AZ_JOB_NAME="$JOB"
  export AZ_IDENTITY_NAME="$IDENTITY" AZ_CONTAINER="$CONTAINER"
  export AZ_SOURCE_PATH_QUALIFIED=YES AZ_QUOTE_ACCEPTED=YES
  export AZ_AUTHORIZE_RESOURCE_CREATION=YES
  bash azure/deploy.sh

MANUAL ONLY; REQUIRES SEPARATE JOB-START APPROVAL:
  az containerapp job start -g "$RG" -n "$JOB"
  az containerapp job execution list -g "$RG" -n "$JOB" -o table
  az containerapp job logs show -g "$RG" -n "$JOB" --container "$JOB" --tail 100

READ-ONLY TEARDOWN PREVIEW:
  AZ_RESOURCE_GROUP="$RG" bash azure/teardown_preview.sh

NO DELETE COMMAND IS EXECUTED BY THIS PLAN.
See docs/AZURE_LIMITED_ACCESS_AND_MILESTONES_20261101.md for scoped roles,
budget caveats, full acceptance blockers, retention, and cleanup steps.
EOF
