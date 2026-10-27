#!/usr/bin/env bash
# No live retailer contact. Run the fixture validation suite before Azure deployment.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m compileall -q walmart_azure
python -m walmart_azure validate --catalog examples/SYNTHETIC_RECORD_NOT_FOR_CONTEST.json
python -m pytest -q
bash -n azure/deploy.sh
printf 'Offline qualification complete. LIVE Walmart and Azure qualification are still required.\n'
