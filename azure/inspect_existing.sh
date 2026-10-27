#!/usr/bin/env bash
# READ ONLY: no storage, build, deployment, or job-start requests.
set -euo pipefail
command -v az >/dev/null || { echo 'Azure CLI required'; exit 2; }
az account show --query '{subscription:id,tenant:tenantId,state:state}' -o json
: "${AZ_RESOURCE_GROUP:?Set the existing AZ_RESOURCE_GROUP supplied by the client}"
az group show --name "$AZ_RESOURCE_GROUP" --query '{id:id,location:location}' -o json
if [[ -n "${AZ_JOB_NAME:-}" ]]; then
  az containerapp job show --resource-group "$AZ_RESOURCE_GROUP" --name "$AZ_JOB_NAME" \
    --query '{id:id,provisioningState:properties.provisioningState,triggerType:properties.configuration.triggerType}' -o json
fi
if [[ -n "${AZ_STORAGE_ACCOUNT:-}" ]]; then
  az storage account show -g "$AZ_RESOURCE_GROUP" -n "$AZ_STORAGE_ACCOUNT" \
    --query '{id:id,kind:kind,location:location,publicNetworkAccess:publicNetworkAccess}' -o json
fi
printf 'READ_ONLY_AZURE_INSPECTION_COMPLETE\n'
