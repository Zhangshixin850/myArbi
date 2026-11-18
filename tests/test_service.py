from decimal import Decimal as D
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from backend.config import Settings
from backend.db import database
from backend.main import LegInput, create_app
from backend.models import Base, Card, Event, Cursor
from backend.service import Service, card_view
from tests.test_ledger import fill


class FakeExchange:
    def __init__(self, product):
        self.product=product
        self.markets={'BTCUSDT':dict(symbol='BTCUSDT',base='BTC',step='.001')}
        self.cache={}
        self.fills=[]
        self.income=[]
        self.qty='0'
        self.fail=False

    async def fetch_markets(self):
        return list(self.markets.values())

    async def fetch_account_risk(self):
        return dict(positions=[dict(symbol='BTCUSDT',positionSide='BOTH',positionAmt=self.qty)],balances={'BTC':self.qty},mode='BOTH',equity='1000',leverage='0',margin_usage='0',adl=[])

    async def fetch_fills(self,symbol,start,end):
        if self.fail:
            raise RuntimeError('sensitive error must not escape')
        return [dict(**x,raw={}) for x in self.fills if start<=x['time']<=end]

    async def fetch_funding_payments(self,symbol,start,end):
        return [dict(**x,raw={}) for x in self.income if start<=x['time']<=end]

    async def fetch_market_snapshot(self,symbol):
        return dict(mark='110',rate='0.0001')

    async def close(self):
        pass


@pytest.fixture
def context(tmp_path):
    engine,sessions=database('sqlite:///'+str(tmp_path/'test.db'))
    Base.metadata.create_all(engine)
    settings=Settings(_env_file=None,app_password='test-secret')
    adapters={('binance','spot'):FakeExchange('spot'),('aster','perp'):FakeExchange('perp')}
    service=Service(sessions,adapters,settings)
    yield service,sessions,adapters,settings
    engine.dispose()


async def new_card(service):
    return await service.create_card([LegInput(account='binance',product='spot',symbol='BTCUSDT',direction='LONG'),
                                     LegInput(account='aster',product='perp',symbol='BTCUSDT',direction='SHORT')])


@pytest.mark.asyncio
async def test_full_cycle_replay_archive_late_funding(context):
    service,sessions,adapters,settings=context
    card_id=await new_card(service)
    with sessions() as db:
        card=db.get(Card,card_id); start=card.started_at; ids=[l.id for l in card.legs]
    for i,adapter in enumerate(adapters.values()):
        adapter.fills=[fill(1,'BUY' if i==0 else 'SELL','1','100'),fill(2,'SELL' if i==0 else 'BUY','1','110')]
        for j,event in enumerate(adapter.fills):event['time']=start+1000+j*1000
    for leg_id in ids:
        await service.sync_leg(leg_id,start+3000)
        await service.sync_leg(leg_id,start+3000)
    service.reconcile(card_id,start+3000)
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Event))==4
        assert db.get(Card,card_id).status=='reconciling'
    for leg_id in ids:await service.sync_leg(leg_id,start+63000)
    service.reconcile(card_id,start+63000)
    with sessions() as db:
        card=db.get(Card,card_id)
        assert card.status=='archived'
        assert not any(l.reserved for l in card.legs)
        assert D(card_view(db,card,settings)['net'])==0
    adapters['aster','perp'].income=[dict(kind='income',external_id='FUNDING_FEE:9',time=start+1500,data=dict(type='FUNDING_FEE',amount='4',asset='USDT'))]
    await service.sync_leg(ids[1],start+86400000)
    with sessions() as db:
        assert D(card_view(db,db.get(Card,card_id),settings)['net'])==4
    # New service sees persisted progress after restart.
    restarted=Service(sessions,adapters,settings)
    await restarted.sync_leg(ids[1],start+86400001)
    with sessions() as db:assert db.scalar(select(func.count()).select_from(Event))==5


@pytest.mark.asyncio
async def test_duplicate_existing_position_and_failure(context):
    service,sessions,adapters,_=context
    adapters['aster','perp'].qty='-1'
    with pytest.raises(ValueError,match='已有仓位'):await new_card(service)
    adapters['aster','perp'].qty='0'
    card_id=await new_card(service)
    with pytest.raises(ValueError,match='占用'):await new_card(service)
    adapters['aster','perp'].fail=True
    await service.sync_once()
    with sessions() as db:
        card=db.get(Card,card_id)
        assert card.status=='reconciling'
        assert 'sensitive' not in card.legs[1].error
        assert db.get(Cursor,f'{card.legs[1].id}:fills') is None


def test_api_auth_and_secrets(context):
    _,sessions,adapters,settings=context
    app=create_app(settings,adapters,sessions,background=False)
    with TestClient(app) as client:
        assert client.get('/api/v1/accounts').status_code==401
        response=client.get('/api/v1/accounts',auth=('admin','test-secret'))
        assert response.status_code==200
        assert 'test-secret' not in response.text
        assert response.json()['execution_enabled'] is False
        assert client.post('/api/v1/execution',auth=('admin','test-secret')).status_code==404


def test_api_create_conflict_details_and_cancel(context):
    _,sessions,adapters,settings=context
    app=create_app(settings,adapters,sessions,background=False)
    with TestClient(app) as client:
        client.auth=('admin','test-secret')
        body={'legs':[dict(account='binance',product='spot',symbol='BTCUSDT',direction='LONG'),
                      dict(account='aster',product='perp',symbol='BTCUSDT',direction='SHORT')]}
        response=client.post('/api/v1/cards',json=body)
        assert response.status_code==201
        card_id=response.json()['id']
        assert client.post('/api/v1/cards',json=body).status_code==409
        assert client.get('/api/v1/cards').json()[0]['base']=='BTC'
        assert client.get(f'/api/v1/cards/{card_id}/events').json()==[]
        assert client.post(f'/api/v1/cards/{card_id}/cancel').status_code==200
        assert client.post('/api/v1/cards',json=body).status_code==201


@pytest.mark.asyncio
async def test_single_leg_and_stale_snapshot_do_not_archive(context):
    service,sessions,adapters,_=context
    card_id=await new_card(service)
    with sessions() as db:
        card=db.get(Card,card_id); start=card.started_at; ids=[l.id for l in card.legs]
    adapter=adapters['binance','spot']
    adapter.fills=[fill(1,'BUY','1','100'),fill(2,'SELL','1','100')]
    for i,event in enumerate(adapter.fills):event['time']=start+i+1
    for leg_id in ids:await service.sync_leg(leg_id,start+100)
    service.reconcile(card_id,start+100)
    service.reconcile(card_id,start+60100)
    with sessions() as db:
        card=db.get(Card,card_id)
        assert card.status!='archived'
        assert all(l.reserved for l in card.legs)


@pytest.mark.asyncio
async def test_late_aster_commission_corrects_fee_sign(context):
    service,sessions,adapters,settings=context
    card_id=await new_card(service)
    with sessions() as db:
        card=db.get(Card,card_id); start=card.started_at; leg_id=card.legs[1].id
    adapter=adapters['aster','perp']
    adapter.qty='-1'
    adapter.fills=[fill(1,'SELL','1','100','-1','USDT','-1')]
    adapter.fills[0]['time']=start+1
    await service.sync_leg(leg_id,start+100)
    with sessions() as db:assert '手续费待估值' in db.get(Card,card_id).legs[1].error
    async def commissions(*args):
        return [dict(kind='income',external_id='COMMISSION:1',time=start+1,
            data=dict(type='COMMISSION',amount='-1',asset='USDT'),raw=dict(tradeId='1'))]
    adapter.fetch_funding_payments=commissions
    await service.sync_leg(leg_id,start+200)
    with sessions() as db:
        view=card_view(db,db.get(Card,card_id),settings)
        assert view['legs'][1]['error'] is None
        assert D(view['legs'][1]['fees'])==1
        assert D(view['legs'][1]['net'])==-1
