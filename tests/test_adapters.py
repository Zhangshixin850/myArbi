import hashlib
import hmac
from urllib.parse import parse_qs

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_typed_data

from backend.adapters import Exchange, ExchangeError
from backend.config import Settings


@pytest.mark.asyncio
async def test_binance_signature_and_only_get():
    def handler(request):
        assert request.method == 'GET'
        if request.url.path.endswith('/time'):
            return httpx.Response(200,json={'serverTime':1700000000000})
        raw=request.url.query.decode()
        payload,signature=raw.rsplit('&signature=',1)
        assert signature==hmac.new(b'secret',payload.encode(),hashlib.sha256).hexdigest()
        assert request.headers['X-MBX-APIKEY']=='key'
        return httpx.Response(200,json=[])
    exchange=Exchange('binance','perp',Settings(_env_file=None,binance_api_key='key',binance_api_secret='secret'),httpx.MockTransport(handler))
    assert await exchange.get('/fapi/v1/userTrades',{'symbol':'BTCUSDT'},True)==[]
    await exchange.close()


@pytest.mark.asyncio
async def test_aster_signature_recovers_agent_and_unique_nonce():
    agent=Account.create()
    nonces=[]
    def handler(request):
        assert request.method=='GET'
        if request.url.path.endswith('/time'):
            return httpx.Response(200,json={'serverTime':1700000000000})
        raw=request.url.query.decode()
        payload,signature=raw.rsplit('&signature=',1)
        values=parse_qs(payload)
        assert values['user']==['0x'+'1'*40]
        nonces.append(int(values['nonce'][0]))
        message=encode_typed_data(domain_data={'name':'AsterSignTransaction','version':'1','chainId':1666,'verifyingContract':'0x'+'0'*40},
            message_types={'Message':[{'name':'msg','type':'string'}]},message_data={'msg':payload})
        assert Account.recover_message(message,signature=signature)==agent.address
        return httpx.Response(200,json=[])
    settings=Settings(_env_file=None,aster_user='0x'+'1'*40,aster_signer=agent.address,aster_private_key=agent.key.hex())
    exchange=Exchange('aster','perp',settings,httpx.MockTransport(handler))
    await exchange.get('/fapi/v3/userTrades',private=True)
    await exchange.get('/fapi/v3/userTrades',private=True)
    assert nonces[1]>nonces[0]
    await exchange.close()


@pytest.mark.asyncio
async def test_full_page_time_split_and_overflow():
    exchange=Exchange('binance','spot',Settings(_env_file=None))
    calls=[]
    async def get(path,params,private):
        calls.append((params['startTime'],params['endTime']))
        return [{}]*1000 if params['startTime']!=params['endTime'] else [{'id':params['startTime']}]
    exchange.get=get
    assert await exchange.window_rows('/test','BTCUSDT',1,2)==[{'id':1},{'id':2}]
    assert calls==[(1,2),(1,1),(2,2)]
    async def overflow(*args):return [{}]*1000
    exchange.get=overflow
    with pytest.raises(ExchangeError,match='单毫秒'):await exchange.window_rows('/test','BTCUSDT',1,1)
    await exchange.close()


@pytest.mark.asyncio
async def test_aster_income_pages_fixed_end_and_error_redaction():
    exchange=Exchange('aster','perp',Settings(_env_file=None))
    calls=[]
    async def get(path,params,private):
        calls.append(params.copy())
        return dict(hasMore=params['page']==1,rows=[dict(incomeType='FUNDING_FEE',tranId=params['page'],time=100,asset='USDT',income='1')])
    exchange.get=get
    rows=await exchange.fetch_funding_payments('BTCUSDT',100,200)
    assert len(rows)==2
    assert [p['page'] for p in calls]==[1,2]
    assert all(p['endTime']==200 for p in calls)
    await exchange.close()
    exchange=Exchange('binance','spot',Settings(_env_file=None),httpx.MockTransport(lambda _:httpx.Response(401,text='SECRET')))
    with pytest.raises(ExchangeError) as error:await exchange.get('/test')
    assert 'SECRET' not in str(error.value)
    await exchange.close()
