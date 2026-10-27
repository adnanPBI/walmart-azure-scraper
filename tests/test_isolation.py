"""Independent stores and navigation deny-by-default regression tests."""
import pytest
from types import SimpleNamespace
from walmart_azure.browser import is_allowed_retail_url
from walmart_azure.cli import _run
from walmart_azure.config import Config, Store, Category
from walmart_azure.storage import AzureStorage, ConcurrentRun


@pytest.mark.parametrize('address,allowed', [
    ('https://www.walmart.com/browse/food',True),
    ('https://walmart.com/ip/12345678',True),
    ('http://www.walmart.com/',False),
    ('https://www.walmart.com.attacker.invalid/',False),
    ('https://example.org/',False),
    ('javascript:alert(1)',False),
    ('https://www.walmart.com@evil.test/',False),
])
def test_redirect_domain_allowlist(address,allowed):
    assert is_allowed_retail_url(address) is allowed


@pytest.mark.asyncio
async def test_one_failed_store_does_not_stop_remaining_stores(monkeypatch,tmp_path):
    import walmart_azure.cli as cli
    stores=[Store(x,'72712',f'Store {x}','406 S Walton','Bentonville','AR') for x in ('100','200')]
    config=Config(stores,[Category('Food','Dairy','https://www.walmart.com/browse/food/milk')])
    monkeypatch.setattr(cli, 'load_config', lambda *_: config)
    monkeypatch.setattr(cli, 'create_storage', lambda *_: object())
    seen=[]
    async def fake_run(store, *args, **kwargs):
        seen.append(store.id)
        if store.id == '100':
            raise RuntimeError('synthetic local block')
        return {'status':'PASS','total_unique':500,'reasons':[],'runtime_seconds':1}
    monkeypatch.setattr(cli, 'run_store', fake_run)
    args=SimpleNamespace(categories='unused',stores='unused',store='',storage='local',
                         output=str(tmp_path),run_id='fake',headed=False)
    assert await _run(args)==2
    assert seen==['100','200']


def test_azure_publish_fails_closed_without_store_lease():
    storage=AzureStorage.__new__(AzureStorage)
    storage._active_leases={}
    with pytest.raises(ConcurrentRun,match='acquired store lease'):
        storage.publish('100',{'status':'PASS'})
