#!/usr/bin/env bash
# READ ONLY. Requires az login but performs zero resource writes or deletes.
set -euo pipefail
: "${AZ_RESOURCE_GROUP:?Set approved dedicated AZ_RESOURCE_GROUP}"
if [[ ! "$AZ_RESOURCE_GROUP" =~ ^rg-walmart72-[a-z0-9-]+$ ]]; then
  echo "STOP: never preview a shared/production resource group" >&2
  exit 2
fi
command -v az >/dev/null || { echo "az CLI required; no action taken" >&2; exit 2; }
PURPOSE="$(az group show -n "$AZ_RESOURCE_GROUP" --query 'tags.purpose' -o tsv)"
if [[ "$PURPOSE" != "walmart72-temporary" ]]; then
  echo "STOP: dedicated purpose=walmart72-temporary tag missing" >&2
  exit 2
fi
printf 'READ ONLY inventory of %s\n' "$AZ_RESOURCE_GROUP"
az account show --query '{subscription:id,tenant:tenantId}' -o json
az group show -n "$AZ_RESOURCE_GROUP" --query '{name:name,location:location,tags:tags,id:id}' -o json
az resource list -g "$AZ_RESOURCE_GROUP" --query '[].{name:name,type:type,id:id}' -o table
az lock list -g "$AZ_RESOURCE_GROUP" -o table
printf '\nNO RESOURCES HAVE BEEN DELETED.\n'
printf 'Client must export evidence first and verify there are no shared/unrelated resources.\n'
printf 'A separate authorized client operator may then issue az group delete -n "%s" --yes\n' "$AZ_RESOURCE_GROUP"
printf 'Deletion removes all RG resources and can cause irreversible data loss.\n'
