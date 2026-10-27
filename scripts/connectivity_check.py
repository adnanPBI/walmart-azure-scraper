"""One non-authenticated HEAD request for environment/network evidence only.

This does NOT attempt a Walmart crawl or prove a selected store or offer.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import argparse
import hashlib
import json
import time


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--url', default='https://www.walmart.com/cp/food/976759')
    p.add_argument('--output', default='docs/observed_connectivity.json')
    args=p.parse_args()
    if urlparse(args.url).hostname not in ('walmart.com', 'www.walmart.com') or not args.url.startswith('https://'):
        raise SystemExit('Only https://www.walmart.com URLs permitted')
    start=time.monotonic()
    report={
        'kind':'environment_connectivity_only_NOT_WALMART_COLLECTION',
        'attempted_utc':datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'url':args.url,'method':'HEAD','request_attempts':1,
        'http_status':None,'verified_store':False,'verified_prices':0,'collected_products':0,
        'buyer_acceptance':'NOT_CERTIFIED'
    }
    try:
        with urlopen(Request(args.url,method='HEAD',headers={'User-Agent':'Mozilla/5.0'}),timeout=8) as response:
            report['http_status']=response.status
            report['response_url_host']=urlparse(response.url).hostname
            report['outcome']='HTTP_RECEIVED_NOT_PRICE_PROOF'
    except HTTPError as exc:
        report['http_status']=exc.code
        report['outcome']='HTTP_ERROR_STOP'
        report['exception_type']='HTTPError'
    except (URLError,TimeoutError,OSError) as exc:
        report['outcome']='LOCAL_NETWORK_ERROR_NOT_RETAILER_RESPONSE'
        report['exception_type']=type(exc).__name__
        report['exception_summary']=str(exc)[:240]
    report['elapsed_seconds']=round(time.monotonic()-start,3)
    dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    main()
