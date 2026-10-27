#!/usr/bin/env bash
# Manual-only, cost-gated Azure diagnostic deployment. No paid Oxylabs requests by default.
# Container default is dry-run only: no Oxylabs credentials, paid requests or schedules.
# This Classic probe uses --max-requests for billable API calls; the prior
# Playwright browser probe uses --max-http-requests for browser network calls.
# They are separate limits and must not be conflated.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${AZ_RESOURCE_GROUP:?Set AZ_RESOURCE_GROUP}"
: "${AZ_REGION:?Set AZ_REGION (e.g. eastus2)}"
: "${AZ_STORAGE_ACCOUNT:?Set globally unique AZ_STORAGE_ACCOUNT}"
: "${AZ_ACR_NAME:?Set globally unique AZ_ACR_NAME}"
AZ_JOB_NAME="${AZ_JOB_NAME:-walmart-pickup-crawler}"
AZ_ENV_NAME="${AZ_ENV_NAME:-walmart-crawler-env}"
AZ_IDENTITY_NAME="${AZ_IDENTITY_NAME:-walmart-crawler-id}"
AZ_CONTAINER="${AZ_CONTAINER:-walmart-scraper}"
AZ_SCHEDULE="${AZ_SCHEDULE:-0 5 * * 1,4}"  # Monday and Thursday at 05:00 UTC
AZ_JOB_RUN_TIMEOUT_SECONDS="${AZ_JOB_RUN_TIMEOUT_SECONDS:-180}" # dry-run bounded diagnostic
AZ_JOB_CPU="${AZ_JOB_CPU:-0.5}"
AZ_JOB_MEMORY="${AZ_JOB_MEMORY:-1.0Gi}"
# A client quote and positive consent must precede any billable resource creation.
if [[ "${AZ_AUTHORIZE_RESOURCE_CREATION:-NO}" != "YES" || "${AZ_QUOTE_ACCEPTED:-NO}" != "YES" ]]; then
  echo 'STOP: This is an infrastructure CREATION script. Obtain a client-approved resource/cost quote first.' >&2
  echo 'For the minimal diagnostic, use azure/inspect_existing.sh (read-only) and an existing job if available.' >&2
  exit 4
fi
# Do not schedule unqualified live collection by accident. Manual trigger by default.
AZ_AUTHORIZE_SCHEDULED_RUNS="${AZ_AUTHORIZE_SCHEDULED_RUNS:-NO}"
if [[ "$AZ_AUTHORIZE_SCHEDULED_RUNS" == "YES" ]]; then
  echo 'STOP: schedule activation is not permitted in the diagnostic deployment script.' >&2
  exit 6
fi
TAG="${AZ_IMAGE_TAG:-$(date -u +%Y%m%d%H%M%S)}"

for file in config/categories.csv config/stores.yaml; do
  if [[ ! -s "$file" ]]; then
    echo "ERROR: required real client configuration missing: $file" >&2
    exit 2
  fi
done
python -m walmart_azure preflight --categories config/categories.csv --stores config/stores.yaml
# It is unsafe to bake an operator's private/local store data into an image.
# The baked public store profile must exactly match the reviewed deployment target.
if ! cmp -s config/stores.yaml config/stores.azure.yaml; then
  echo 'STOP: config/stores.yaml differs from public Azure image config/stores.azure.yaml' >&2
  echo 'Synchronize non-secret public store details first; never bake browser cookies/session_state.' >&2
  exit 5
fi

command -v az >/dev/null || { echo 'Azure CLI az required' >&2; exit 2; }
az account show --query '{subscription:id, tenant:tenantId}' -o json
read -r -p 'Deploy into the displayed Azure subscription? Type DEPLOY: ' ANSWER
[[ "$ANSWER" == "DEPLOY" ]] || exit 3
az extension add --name containerapp --upgrade --yes >/dev/null
if az containerapp job show -g "$AZ_RESOURCE_GROUP" -n "$AZ_JOB_NAME" --output none 2>/dev/null; then
  echo 'STOP: existing Container Apps job found. No costed builds or changes attempted.' >&2
  exit 7
fi
az group create -n "$AZ_RESOURCE_GROUP" -l "$AZ_REGION" --output none
if ! az storage account show -g "$AZ_RESOURCE_GROUP" -n "$AZ_STORAGE_ACCOUNT" --output none 2>/dev/null; then
  az storage account create -g "$AZ_RESOURCE_GROUP" -n "$AZ_STORAGE_ACCOUNT" -l "$AZ_REGION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false --output none
fi
if ! az acr show -g "$AZ_RESOURCE_GROUP" -n "$AZ_ACR_NAME" --output none 2>/dev/null; then
  az acr create -g "$AZ_RESOURCE_GROUP" -n "$AZ_ACR_NAME" --sku Basic --admin-enabled false --output none
fi
if ! az identity show -g "$AZ_RESOURCE_GROUP" -n "$AZ_IDENTITY_NAME" --output none 2>/dev/null; then
  az identity create -g "$AZ_RESOURCE_GROUP" -n "$AZ_IDENTITY_NAME" --output none
fi
IDENTITY_ID="$(az identity show -g "$AZ_RESOURCE_GROUP" -n "$AZ_IDENTITY_NAME" --query id -o tsv)"
IDENTITY_PRINCIPAL="$(az identity show -g "$AZ_RESOURCE_GROUP" -n "$AZ_IDENTITY_NAME" --query principalId -o tsv)"
IDENTITY_CLIENT="$(az identity show -g "$AZ_RESOURCE_GROUP" -n "$AZ_IDENTITY_NAME" --query clientId -o tsv)"
ACR_ID="$(az acr show -g "$AZ_RESOURCE_GROUP" -n "$AZ_ACR_NAME" --query id -o tsv)"
STORAGE_ID="$(az storage account show -g "$AZ_RESOURCE_GROUP" -n "$AZ_STORAGE_ACCOUNT" --query id -o tsv)"
# Role assignments are idempotent for the principal, role and resource scope.
for role_scope in "AcrPull|$ACR_ID" "Storage Blob Data Contributor|$STORAGE_ID"; do
  role="${role_scope%%|*}"; scope="${role_scope#*|}"
  if [[ "$(az role assignment list --assignee "$IDENTITY_PRINCIPAL" --scope "$scope" --role "$role" --query 'length(@)' -o tsv)" == "0" ]]; then
    az role assignment create --assignee-object-id "$IDENTITY_PRINCIPAL" --assignee-principal-type ServicePrincipal \
      --role "$role" --scope "$scope" --output none
  fi
done
# Current Azure CLI operator must have Storage Blob Data Contributor in order to
# create the container without passing a storage-account key into source code.
az storage container create --account-name "$AZ_STORAGE_ACCOUNT" --name "$AZ_CONTAINER" \
  --auth-mode login --output none
if ! az containerapp env show -g "$AZ_RESOURCE_GROUP" -n "$AZ_ENV_NAME" --output none 2>/dev/null; then
  az containerapp env create -g "$AZ_RESOURCE_GROUP" -n "$AZ_ENV_NAME" -l "$AZ_REGION" --output none
fi
IMAGE="${AZ_ACR_NAME}.azurecr.io/walmart-pickup-crawler:${TAG}"
# Builds remotely in ACR, avoiding local Docker installation requirements.
az acr build --registry "$AZ_ACR_NAME" --image "walmart-pickup-crawler:${TAG}" --file Dockerfile.classic .

if az containerapp job show -g "$AZ_RESOURCE_GROUP" -n "$AZ_JOB_NAME" --output none 2>/dev/null; then
  echo 'STOP: job already exists. No silent updates to an existing job or schedule.' >&2
  exit 7
else
  TRIGGER_ARGS=(--trigger-type Manual)
  echo 'SAFETY: diagnostic jobs are MANUAL only. This script never enables scheduling.' 
  az containerapp job create \
    --name "$AZ_JOB_NAME" --resource-group "$AZ_RESOURCE_GROUP" --environment "$AZ_ENV_NAME" \
    "${TRIGGER_ARGS[@]}" \
    --parallelism 1 --replica-completion-count 1 --replica-retry-limit 0 \
    --replica-timeout "$AZ_JOB_RUN_TIMEOUT_SECONDS" --cpu "$AZ_JOB_CPU" --memory "$AZ_JOB_MEMORY" \
    --image "$IMAGE" \
    --args "oxylabs-probe" "--store" "3891" "--max-requests" "1" "--max-retries" "0" "--max-seconds" "90" \
           "--categories" "/opt/scraper/config/categories.csv" \
           "--stores" "/opt/scraper/config/stores.yaml" \
           "--output" "/tmp/oxylabs-classic-dryrun.json" \
    --mi-user-assigned "$IDENTITY_ID" --registry-server "${AZ_ACR_NAME}.azurecr.io" --registry-identity "$IDENTITY_ID" \
    --env-vars "AZURE_CLIENT_ID=$IDENTITY_CLIENT" \
               "AZURE_STORAGE_ACCOUNT_URL=https://${AZ_STORAGE_ACCOUNT}.blob.core.windows.net" \
               "AZURE_STORAGE_CONTAINER=$AZ_CONTAINER" \
               "WALMART_MIN_DELAY_SECONDS=1.5" "WALMART_MAX_DELAY_SECONDS=3.0" \
    --output none
fi
printf '\nDeployed job: %s\nImage: %s\nRequested UTC schedule: %s\nScheduled execution authorized: %s\n' "$AZ_JOB_NAME" "$IMAGE" "$AZ_SCHEDULE" "$AZ_AUTHORIZE_SCHEDULED_RUNS"
printf '\nStart the BOUNDED DIAGNOSTIC only after the client authorizes it:\n'
printf 'az containerapp job start -g %s -n %s\n' "$AZ_RESOURCE_GROUP" "$AZ_JOB_NAME"
printf 'az containerapp job execution list -g %s -n %s -o table\n' "$AZ_RESOURCE_GROUP" "$AZ_JOB_NAME"
printf 'NOTE: Azure permissions and retailer access must be qualified independently.\n'
