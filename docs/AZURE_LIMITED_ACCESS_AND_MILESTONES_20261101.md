# Walmart Contest #72 — Azure limited-access, quote and milestone plan

**Prepared:** November 1, 2026, Asia/Dhaka (UTC+06:00).
**Source version:** Walmart Azure Scraper **v0.5.7**, exact GitHub commit is the
only authoritative source. This is a **review/quote and preflight addendum**.
It is **NOT** an Azure deployment, a paid Classic request, a production
collector integration, a demonstrated Walmart dataset, or a contest award.

## 0. Current gates / the client's decision

The client has credited v0.5.7's fail-closed terminal publication and
phase-deadline disclosure. **Do NOT repeat that correction.**

Before ANY paid retailer call:
- The client confirms its **Classic Oxylabs Web Scraper API** account has
  the **walmart_product** source and supports store_id/fulfillment_type.
- The client separately approves **one** billable attempt and the quoted
  account-specific cost; credentials are injected privately by the client.
- Target: client-nominated Great Value Whole Vitamin D Milk, Gallon,
  ID **10450114**, URL **https://www.walmart.com/ip/10450114**.
- Request: `source=walmart_product`, `product_id=10450114`,
  `store_id=3891`, `fulfillment_type=pickup`, `parse=false`,
  `render=""`. Exactly **one request**, **zero retries**, **90-second
  PHASE deadline** (NOT hard total command runtime), **2,000,000-byte
  response cap**; no rendering, no automatic follow-up calls.
- The returned retailer HTML must independently prove Walmart Waukegan
  #3891 PICKUP AND that exact monetary context. Configured parameters do
  not constitute source proof. Preserve sanitized provider response, hash,
  actual returned URL/job ID, qualified first-party price, directly
  scraped PPM and complete separate offer terms. Genuine verified count
  remains zero until independent authentication.

**Azure source gate:** The client explicitly asks that Azure spending and
deployment FOLLOW a usable, independently reviewed source path. Do not
run the Azure deployment script while this gate remains false.

## 1. Exact temporary Azure resource list — manual diagnostic only

**Owner:** client; **region example:** eastus2 (confirm available region
and client-specific prices). **Group:** pre-create a dedicated RG named
`rg-walmart72-review-202611`, tag `purpose=walmart72-temporary`,
`owner=client`. Never use an existing shared or production group.

| Resource | Example name / size | Access / what it proves |
| --- | --- | --- |
| 1 Azure Resource Group | `rg-walmart72-review-202611` | Dedicated, tagged, client-owned, reversible scope |
| 1 Azure Container Registry | `acrwalmart72<unique>`, Basic, admin user OFF | Remote `az acr build` of **Dockerfile.classic**, no retailer call |
| 1 StorageV2 account | `stwalmart72<unique>`, Standard_LRS, TLS >=1.2, anonymous Blob OFF | Review-only private storage target; **not yet verified** |
| 1 private Blob container | `walmart72-evidence` | Later sanitized evidence + checkpoint/output retention |
| 1 user-assigned managed identity | `walmart72-job-identity` | ACR image pull + RBAC on exactly the Blob container |
| 1 Container Apps environment | `walmart72-diagnostic-env`, consumption | Small isolated execution environment |
| 1 Container Apps Job | `walmart72-classic-job`: **Manual**, 1 parallel replica, 0 retries, 0.5 vCPU, 1 GiB, **180-second replica timeout** | ZERO-COST *retailer* dry-run; no automatic scheduling, credentials or live source claims |
| Optional dedicated Log Analytics workspace | `law-walmart72-review`, short retention, client-approved | Durable post-run logs: separate charge and IAM approval; NOT auto-created by the default safe script |
| Optional later Key Vault | Client-owned vault with secrets + job identity scoped access | Only if paid production integration is separately authorized; excluded from first dry-run |

The existing **`azure/deploy.sh`** now requires: (a) source gate
`AZ_SOURCE_PATH_QUALIFIED=YES`, (b) explicit quote approval
`AZ_QUOTE_ACCEPTED=YES`, and (c) resource creation approval
`AZ_AUTHORIZE_RESOURCE_CREATION=YES`. It refuses absent/mis-tagged/
shared RGs; it **never creates the RG** itself. It compares the parsed
YAML content of `config/stores.yaml` against the bundled
`config/stores.azure.yaml` so harmless comment differences do not fail,
but real store, limit or extra-key differences are rejected. A qualified client admin
creates/approves the RG. Dockerfile.classic and the manual job default to
a **dry-run of product 10450114** with 0 provider requests. No credentials,
`--execute-billable` or schedule are injected.

**Caller return deadline:** the scraper's `--max-seconds=90` applies to
provider/worker processing and fail-closed staging, **not** an unconditional
command/caller wall-clock bound. A blocking synchronous terminal file commit
can extend caller runtime beyond the phase deadline; after it completes the
verdict fails closed and the pre-dispatch request remains reserved. This
v0.5.7 contract has been credited by the client and is unchanged.

**Paid production blocker:** the Classic approval ledger is file-backed and
must remain **durable, single-writer, and shared across restarts/replicas**.
Container Apps local `/tmp` is ephemeral. The dry-run container has no
approved credentials and MUST NOT be promoted into billable or scheduled
production merely by adding secrets. Full integration must provide an
independently tested persistent shared ledger/lease transaction model before
any paid Azure execution, plus source-bound storage proof and client approval.

The default job's `/tmp` dry-run receipt is **ephemeral** and does
**NOT** prove Blob upload, published product datasets, Log Analytics
retention or Azure recovery. Those are separate full-acceptance gates.
Initial environment disables persistent logs deliberately to avoid
creating an unquoted workspace; run logs can be streamed while active,
but only separately approved retained logging establishes a durable
audit record.

## 2. Exact narrowly scoped RBAC / who does what

**Recommended first choice: CLIENT-OPERATED deployment or attended session.**
No blanket subscription Owner/Contributor for the developer and no
downloadable passwords.

| Principal | Role and exact scope | Purpose / limitation |
| --- | --- | --- |
| Client Azure admin (client retains) | Subscription permissions to create a new RG; built-in **Contributor** role scoped ONLY to that temporary RG (or an equivalent narrower custom role); role-assignment privilege held **only by client admin** | Create/tear down scoped resources, assign identities. Does not transfer subscription rights |
| Developer, *before Azure access is approved* | **Reader** on the dedicated RG, optional | Read-only proposed configuration and execution inventory; no job start or resource changes |
| Developer/reviewer, if needed | **Storage Blob Data Reader** on `$STORAGE_ID/blobServices/default/containers/walmart72-evidence` | Inspect evidence in one specific container; not other customer data |
| Developer/reviewer, if logs retained | **Log Analytics Reader** on exact test workspace | Inspect test logs; no broad Monitor privileges |
| Client-operator for one approved manual execution | **Container Apps Jobs Operator** scoped to the exact job resource, temporarily granted; otherwise client operator starts it | Role permits read/start/stop AND logstream/exec, so grant carefully and revoke after test |
| Client-operated build identity/user | **Container Registry Tasks Contributor** scoped to test ACR (for `az acr build`) | Allows quick builds; not necessary for developer if client builds |
| Client-operated provisioner | **Container Apps Jobs Contributor** on test job, **Container Apps ManagedEnvironments Contributor** on test environment; **Managed Identity Operator** on selected identity if required | Deployment only; narrower than subscription-wide Contributor |
| Runtime user-assigned managed identity | **AcrPull** scoped to the test ACR (for standard registry RBAC), **Storage Blob Data Contributor** on the **one Blob container** | Read the image + eventually write evidence. An ABAC-enabled registry may require the repository-reader role instead |
| Client admin for RBAC grants | RBAC role-assignment permissions limited to temporary resources | Needed to assign roles; do not give broad role-assignment power to the developer |

Azure Blob data roles are distinct from ordinary resource-management
Reader/Contributor roles. The Azure CLI login that creates the container
requires Blob Data Contributor (or equivalent). A delegated creator may
need narrowly scoped extra resource-creation roles; **client admin should
perform that setup**, not hand over root-level access.

Official role references:
https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/containers
https://learn.microsoft.com/en-us/azure/storage/blobs/assign-azure-role-data-access
https://learn.microsoft.com/en-us/azure/container-registry/container-registry-rbac-built-in-roles-directory-reference

## 3. Exact build, run, logs and storage commands (NOT EXECUTED)

From the **checked-out authoritative commit**, Linux, macOS, WSL or Azure
Cloud Shell with Azure CLI and Bash. Environment variable names in the
repository script are authoritative. A client should **first** review
`bash azure/plan_client_review.sh`, which only prints commands.

```bash
# READ-ONLY account context, after temporary access is granted:
az login
az account show --query '{subscription:id,tenant:tenantId}' -o json
export AZ_RESOURCE_GROUP=rg-walmart72-review-202611
export AZ_REGION=eastus2
export AZ_ACR_NAME=acrwalmart72YOURUNIQUE
export AZ_STORAGE_ACCOUNT=stwalmart72YOURUNIQUE
export AZ_ENV_NAME=walmart72-diagnostic-env
export AZ_JOB_NAME=walmart72-classic-job
export AZ_IDENTITY_NAME=walmart72-job-identity
export AZ_CONTAINER=walmart72-evidence

# CLIENT ADMIN ONLY, after quote and source qualification:
az group create -n "$AZ_RESOURCE_GROUP" -l "$AZ_REGION" \
  --tags purpose=walmart72-temporary owner=client

# PRINT-ONLY REVIEW FIRST (creates nothing):
bash azure/plan_client_review.sh

# CLIENT-APPROVED creation; guarded and manual-only:
AZ_SOURCE_PATH_QUALIFIED=YES AZ_QUOTE_ACCEPTED=YES \
  AZ_AUTHORIZE_RESOURCE_CREATION=YES bash azure/deploy.sh

# Separate, client-approved MANUAL dry-run execution:
az containerapp job start -g "$AZ_RESOURCE_GROUP" -n "$AZ_JOB_NAME"
az containerapp job execution list -g "$AZ_RESOURCE_GROUP" \
  -n "$AZ_JOB_NAME" -o table
# Discover actual container name, then stream when available:
az containerapp job show -g "$AZ_RESOURCE_GROUP" -n "$AZ_JOB_NAME" \
  --query 'properties.template.containers[].name' -o tsv
az containerapp job logs show -g "$AZ_RESOURCE_GROUP" \
  -n "$AZ_JOB_NAME" --container "$AZ_JOB_NAME" --tail 100

# Read-only Blob inventory (initial dry-run may be empty; that is expected):
az storage blob list --account-name "$AZ_STORAGE_ACCOUNT" \
  --container-name "$AZ_CONTAINER" --auth-mode login -o table

# Audit the inventory before ANY deletion:
bash azure/teardown_preview.sh
```

`az containerapp job logs show` is an Azure CLI extension/preview API
and requires a valid container name (replace the example with the output
of the preceding `job show`). Without durable logging configured, the
stream may not be available once the execution ends. A full acceptance
run must persist sanitized job traces and hashes to client-approved
Blob storage and/or a client-approved Log Analytics workspace.

Existing `azure/deploy.sh` provisions only the **review-only manual
dry-run** job. It does not start the job, grant paid Oxylabs access,
connect the real production Classic collector, prove Blob evidence writes,
or enable twice-weekly scheduling.

## 4. Azure provisional build/run/storage/log costs — NOT a price quote

**Example window:** no more than **72 hours** of temporary resources,
**up to 3 manual executions** after separate client approval; **each at
most 180 s**, one 0.5-vCPU / 1-GiB replica, zero retries. This is a
quantity-based budget envelope, not permission to consume it.

| Meter | Maximum *planned usage* | Cost note |
| --- | --- | --- |
| Container Apps compute | `3 × 180 × 0.5 = 270 vCPU-seconds` and `3 × 180 × 1 = 540 GiB-seconds` | Often inside the subscription's monthly free **180,000 vCPU-s/360,000 GiB-s** grant *if available*; check other usage |
| ACR Basic registry | 1 registry for <=72 hours | Recurring tier charge while it exists; also price `az acr build` quick-build usage separately |
| Standard_LRS Hot Blob | Plan <=1 GiB of sanitized output, <=1,000 write/read/list transactions | Small but not automatically free; verify with region calculator |
| Log Analytics / Azure Monitor | None in default dry-run; optional <=0.25 GiB ingestion if retained logs approved | Ingestion and retention priced by workspace/region; seek separate approval |
| Data transfer | Minimal to zero in offline dry run; actual live source and output transfers are unqualified | Egress, private networking, managed environment and tax may add charges |
| Oxylabs Classic | **ZERO paid requests authorized**; future one-call limit separately approved | **NOT covered** by Azure credits; supplier's account quote required |

**Indicative approval planning envelope:** **USD $10–$25**
for a 72-hour review deployment with 1–3 manual jobs and limited data.
This is a **provisional spending allowance suggestion, not an Azure
retail price quote or technical hard cap**. The actual amount might be
higher depending on region, tax, ACR quick-build time, existing free
allowances, log retention, network, and the Azure agreement.

The client should obtain an exact region/account quote using
https://azure.microsoft.com/pricing/calculator/ **before** setting
`AZ_QUOTE_ACCEPTED=YES`. Azure Cost Management budget alerts are
notifications, **not automated spend caps**, and cost data may lag.
Real risk controls are manual-only triggering, replica timeout=180,
replica retry=0, no scheduled jobs, no paid provider credentials,
an isolated RG and early confirmed deletion.
Cost references:
https://azure.microsoft.com/en-us/pricing/details/container-apps/
https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets
https://learn.microsoft.com/en-us/azure/container-apps/jobs

## 5. Bounded cleanup — client-owned, no deletion from ChatGPT

**Initial expiry:** 72 hours after client approves creation, or earlier
when diagnostic evidence has been reviewed. A client operator should
schedule calendar review **before** that time; budget alerts alone do
not stop service charges.

1. Stop launching jobs; verify no execution remains running
   (`az containerapp job execution list`). Confirm no new schedule.
2. Export and hash any required sanitized evidence, stdout/stderr,
   provider receipt and approval ledger before deletion. A local,
   ephemeral `/tmp` receipt is NOT a backup.
3. Run `AZ_RESOURCE_GROUP="$AZ_RESOURCE_GROUP" bash
   azure/teardown_preview.sh`: **read-only**; confirms dedicated group
   name/tag, subscription, current resources and locks.
4. Client administrator confirms **there are NO shared resources**,
   obtains written deletion approval and preserves accepted proof.
5. Client administrator issues the destructive action **only after
   approval**:

   ```bash
   az group delete --name "$AZ_RESOURCE_GROUP" --yes
   az group exists --name "$AZ_RESOURCE_GROUP"   # expect false
   ```

   Deleting the RG removes the registry, image, storage and retained
   evidence contained in that RG. It is **irreversible**. Do not do
   this if the group has unrelated resources, legal hold, active jobs
   or evidence not yet exported. Revoke temporary scoped identities/
   role assignments after acceptance and verify the final Azure bill.

## 6. Dated milestones (Asia/Dhaka, UTC+06:00)

These are conditional **earliest practical checkpoints**, not a
guaranteed award or delivery dates.

| Date & time | Deliverable | Gate |
| --- | --- | --- |
| **Tue Nov 3, 2026, 18:00 Dhaka (06:00 CST)** | Independently reproducible code/CI, source-access decision status, fixed one-product review plan, Azure resources/role/estimate/teardown plan | **This status checkpoint is committed even if authorization is pending** |
| **Wed Nov 4, 18:00 Dhaka** | One actual Classic `10450114` response with returned job ID/URL and #3891 PICKUP monetary-context review; or blocker report | **ONLY if account entitlement and one-call spend consent are provided in advance** |
| **Fri Nov 6, 18:00 Dhaka** | Production Classic listing/detail adapter integrated behind guarded source qualification; tests and no-delete/retention protections | Conditional on usable raw context and source shape from previous stage |
| **Tue Nov 10, 18:00 Dhaka** | Interim full-tree manifest, uncapped parent/subcategory/pagination audit and multi-category collection evidence | Conditional on lawful source access and available category/navigation data |
| **Thu Nov 12 – Mon Nov 16, 18:00 Dhaka** | 500 genuine distinct products with required source/field checks, observed live stop/resume, manual Azure execution/log/storage evidence and acceptance packet | **Earliest planning range ONLY if connectivity AND complete required coverage are qualified by Thu Nov 5** |

If the above gates are not met by their assumed dates, the corresponding
milestones slide. The previously discussed **5–7 working days starts only
after both connectivity and complete coverage qualification**, and is not
a committed completion date. Final client review is outside the estimate.

**Exact checkpoint due:** November 3, 2026, 18:00 Asia/Dhaka
= November 3, 2026, 06:00 US Central Standard Time (CST; UTC-06:00).

## 7. Specific client actions requested (no credentials via chat)

1. Confirm Classic Walmart `walmart_product` entitlement in the existing
   account; provide account-specific quote for one product request and
   independent approval or refusal **as a separate explicit decision**.
2. If approved, securely configure the provider credentials in the
   authorized testing environment. Do NOT paste credentials or session
   cookies into chat/repo/CI.
3. Confirm the client-nominated product ID `10450114` and approve the
   precise bounded one-call payload as previously proposed; no expansion.
4. Select Azure subscription/region and either (a) operate the CLI with
   the developer in an attended session or (b) later issue **scoped** RBAC
   on a new test resource group; pre-approve a region-specific quote and
   temporary teardown window before any Azure deployment.
5. State whether the optional retained logging workspace is required for
   acceptance, and approve its quoted ingestion/retention cost and
   evidence retention policy.
6. Continue reviewing the **same** original product schema and original
   category CSV. Full production listing coverage and the genuine
   500-product demonstration remain independently required; an
   unavailable or later-missing eligible item is retained indefinitely
   with historical provenance, not filtered by priced diagnostic.

**No new authorization was created by this plan or these scripts.**
