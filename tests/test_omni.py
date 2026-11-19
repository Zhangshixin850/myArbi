from decimal import Decimal as D
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event as sql_event, func, select

from backend.adapters import ExchangeError, Omni
from backend.config import Settings
from backend.db import database
from backend.ledger import calculate_manual
from backend.main import LegInput, ManualPositionInput, create_app
from backend.models import Audit, Base, Card, Cursor, Event, Leg
from backend.service import Service, card_view, events_for
from tests.test_ledger import fill
from tests.test_service import FakeExchange

BASE = 1800000000000
INTERVAL = 3600000


def public_listing(funding=True):
    return dict(ticker='BTC-PERP', contract_type='perpetual', mark_price='100', funding=dict(
        last=dict(annualized_rate='8.76', interval_rate='.001'), next=None,
        interval_seconds=3600, next_timestamp=4102444800) if funding else None)


@pytest.mark.asyncio
async def test_public_v2_units_filter_cache_and_no_private_api():
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        assert request.url.path == '/metadata/v2/stats'
        assert 'signature' not in str(request.url)
        return httpx.Response(200, json=dict(listings=[public_listing(),
            dict(ticker='BTC-SWAP', contract_type='swap'), dict(ticker='BTC', contract_type='perpetual')]))
    adapter = Omni(httpx.MockTransport(handler))
    assert await adapter.fetch_markets() == [dict(symbol='BTC-PERP', base='BTC', quote='USDC', step=None, source='manual')]
    snap = await adapter.fetch_market_snapshot('BTC-PERP')
    assert len(calls) == 1
    assert D(snap['rate']) == D('.001')
    assert D(snap['annualized_rate']) == D('8.76')
    assert D(snap['daily_rate']) == D('.024')
    assert snap['next_funding'] == 4102444800000
    assert all(snap[key] is None for key in ('equity', 'leverage', 'margin_usage', 'adl'))
    with pytest.raises(ExchangeError, match='市场不可用'):
        await adapter.fetch_market_snapshot('BTC-SWAP')
    await adapter.close()


@pytest.mark.asyncio
async def test_public_missing_funding_and_rate_limit():
    adapter = Omni(httpx.MockTransport(lambda _: httpx.Response(200, json=dict(listings=[public_listing(False)]))))
    snap = await adapter.fetch_market_snapshot('BTC-PERP')
    assert snap['rate'] is None and snap['next_funding'] is None
    await adapter.close()
    calls = []
    def limited(request):
        calls.append(request)
        return httpx.Response(429, json=dict(retry_after_seconds=23))
    adapter = Omni(httpx.MockTransport(limited))
    for _ in range(2):
        with pytest.raises(ExchangeError, match='限流') as error:
            await adapter.fetch_markets()
        assert error.value.retry_after >= 22
    assert len(calls) == 1
    await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'listings': None}, {'listings': [dict(public_listing(), mark_price='NaN')]}])
async def test_public_invalid_data_is_not_zero(payload):
    adapter = Omni(httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(ExchangeError):
        await adapter.fetch_market_snapshot('BTC-PERP')
    await adapter.close()


class FakeOmni:
    def __init__(self, clock):
        self.clock = clock
        self.markets = {'BTC-PERP': dict(symbol='BTC-PERP', base='BTC', quote='USDC', step=None)}
        self.cache = {}
        self.node = BASE + 600000
        self.interval = INTERVAL // 1000
        self.funding = True
        self.fail = False

    async def fetch_markets(self):
        return list(self.markets.values())

    async def fetch_market_snapshot(self, symbol):
        if self.fail:
            raise ExchangeError('模拟公共接口离线', 30)
        return dict(mark='100', rate='.001' if self.funding else None,
            next_funding=self.node if self.funding else None, interval_seconds=self.interval,
            observed_at=self.clock[0], equity=None, leverage=None, margin_usage=None, adl=None)

    async def close(self):
        pass


@pytest.fixture
def omni_context(tmp_path, monkeypatch):
    clock = [BASE]
    monkeypatch.setattr('backend.service.now_ms', lambda: clock[0])
    engine, sessions = database('sqlite:///' + str(tmp_path / 'omni.db'))
    Base.metadata.create_all(engine)
    settings = Settings(_env_file=None, app_password='test-secret')
    auto, omni = FakeExchange('perp'), FakeOmni(clock)
    adapters = {('binance', 'perp'): auto, ('omni', 'perp'): omni}
    service = Service(sessions, adapters, settings)
    yield service, sessions, auto, omni, settings, clock
    engine.dispose()


async def new_omni(context, direction='SHORT'):
    service, sessions, _, _, _, _ = context
    card_id = await service.create_card([
        LegInput(account='binance', product='perp', symbol='BTCUSDT', direction='LONG' if direction == 'SHORT' else 'SHORT'),
        LegInput(account='omni', product='perp', symbol='BTC-PERP', direction=direction)])
    with sessions() as db:
        card = db.get(Card, card_id)
        return card_id, card.legs[1].id, card.legs[0].id


def position(revision, qty, average=None, **kwargs):
    return ManualPositionInput(request_id=uuid4(), expected_revision=revision, qty=qty, average=average, **kwargs)


def view(context, card_id):
    _, sessions, _, _, settings, _ = context
    with sessions() as db:
        return card_view(db, db.get(Card, card_id), settings)


@pytest.mark.asyncio
@pytest.mark.parametrize('direction,realized', [('LONG', '20'), ('SHORT', '-20')])
async def test_manual_weighted_add_partial_close_and_clear(omni_context, direction, realized):
    service, sessions, _, _, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context, direction)
    assert view(omni_context, card_id)['imbalance'] is None
    assert view(omni_context, card_id)['legs'][1]['unrealized'] is None
    rows = [position(0, '2', '100', fee='1'), position(1, '3', '110'),
            position(2, '1', '110', close_price='130', fee='2'),
            position(3, '0', close_price='90', confirm_closed=True)]
    for row in rows:
        clock[0] += 1000
        await service.save_manual(card_id, leg_id, row)
    with sessions() as db:
        leg = db.get(Leg, leg_id)
        result = calculate_manual(events_for(db, leg), direction)
        assert D(result['opened']) == 330
        assert D(result['realized']) == D(realized)
        assert D(result['fees']) == 3
        assert D(result['qty']) == 0
        assert result['unrealized'] == '0' and result['closed_confirmed']
        assert result['fills'] == 4


@pytest.mark.asyncio
async def test_manual_idempotency_version_correction_and_offline_save(omni_context):
    service, sessions, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    request = position(0, '2', '100', fee='1')
    omni.fail = True
    assert await service.save_manual(card_id, leg_id, request) == dict(revision=1)
    assert await service.save_manual(card_id, leg_id, request) == dict(revision=1)
    with pytest.raises(ValueError, match='不同内容'):
        await service.save_manual(card_id, leg_id, request.model_copy(update=dict(qty='3')))
    with pytest.raises(ValueError, match='刷新'):
        await service.save_manual(card_id, leg_id, position(0, '3', '100'))
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(1, '2', '120', fee='2', replace_last=True))
    result = view(omni_context, card_id)['legs'][1]
    assert D(result['opened']) == 240 and D(result['fees']) == 2
    assert result['first'] == BASE + 1000
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'manual_position')) == 2
        assert db.scalar(select(Audit).where(Audit.message.like('修订最近%'))) is not None


@pytest.mark.asyncio
async def test_invalid_manual_changes_do_not_advance_version(omni_context):
    service, _, _, _, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '2', '100'))
    cases = [position(1, '3', '50'), position(1, '1', '100'),
             position(1, '0', close_price='110'), position(1, '2', '101'),
             position(1, '3', '100', confirm_closed=True)]
    for body in cases:
        with pytest.raises(ValueError):
            await service.save_manual(card_id, leg_id, body)
    assert view(omni_context, card_id)['legs'][1]['revision'] == 1


@pytest.mark.parametrize('qty', ['NaN', 'Infinity', '-1', '1e1000', '9'*61])
def test_decimal_input_validation(qty):
    with pytest.raises(ValidationError):
        position(0, qty, '100')


@pytest.mark.asyncio
@pytest.mark.parametrize('direction,amount', [('SHORT', '.2'), ('LONG', '-.2')])
async def test_funding_settlement_units_dedup_restart_and_correction(omni_context, direction, amount):
    service, sessions, auto, omni, settings, clock = omni_context
    card_id, leg_id, auto_id = await new_omni(omni_context, direction)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '2', '100'))
    auto.qty = '2' if direction == 'SHORT' else '-2'
    auto.fills = [fill(1, 'BUY' if direction == 'SHORT' else 'SELL', '2', '100')]
    auto.fills[0]['time'] = clock[0]
    node = omni.node
    clock[0] = node - 1000
    await service.sync_leg(leg_id, clock[0])
    clock[0] = node + 1000
    omni.node += INTERVAL
    await service.sync_leg(leg_id, clock[0])
    await service.sync_leg(auto_id, clock[0])
    result = view(omni_context, card_id)
    assert D(result['legs'][1]['estimated_funding']) == D(amount)
    assert result['legs'][1]['funding'] == '0'
    assert D(result['net']) == 0 and D(result['estimated_net']) == D(amount)
    assert result['annual'] is None and result['estimated_annual'] is not None
    restarted = Service(sessions, service.adapters, settings)
    await restarted.sync_leg(leg_id, clock[0])
    await restarted.save_manual(card_id, leg_id, position(1, '3', '100', replace_last=True))
    assert D(view(omni_context, card_id)['legs'][1]['estimated_funding']) == D(amount) * D('1.5')
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'estimated_funding')) == 1
        assert db.get(Cursor, f'{leg_id}:estimated').through == node


@pytest.mark.asyncio
async def test_stale_and_skipped_settlements_remain_missing(omni_context):
    service, sessions, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    clock[0] = omni.node + 2 * INTERVAL + 1000
    omni.node += 3 * INTERVAL
    await service.sync_leg(leg_id, clock[0])
    result = view(omni_context, card_id)
    assert not result['funding_complete'] and result['estimated_annual'] is None
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'estimated_funding')) == 0
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'estimated_funding_gap')) == 2


@pytest.mark.asyncio
async def test_missing_funding_can_close_and_archive_with_disclosure(omni_context):
    service, sessions, auto, omni, _, clock = omni_context
    omni.funding = False
    card_id, leg_id, auto_id = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(1, '0', close_price='100', confirm_closed=True))
    auto.fills = [fill(1, 'BUY', '1', '100'), fill(2, 'SELL', '1', '100')]
    for i, event in enumerate(auto.fills):
        event['time'] = BASE + i + 1
    for _ in range(2):
        await service.sync_leg(auto_id, clock[0])
        service.reconcile(card_id, clock[0])
        clock[0] += 60000
    result = view(omni_context, card_id)
    assert result['status'] == 'archived'
    assert not result['complete'] and not result['funding_complete']
    assert result['estimated_net'] is None
    with pytest.raises(ValueError, match='已结束'):
        await service.save_manual(card_id, leg_id, position(2, '1', '100'))
    with sessions() as db:
        assert not db.get(Leg, leg_id).reserved


@pytest.mark.asyncio
async def test_offline_close_retains_unknown_later_payments(omni_context):
    service, sessions, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    clock[0] = omni.node - 1000
    await service.sync_leg(leg_id, clock[0])
    clock[0] = omni.node + 3 * INTERVAL
    omni.fail = True
    await service.save_manual(card_id, leg_id, position(1, '0', close_price='100', confirm_closed=True))
    leg = view(omni_context, card_id)['legs'][1]
    assert D(leg['estimated_funding']) == D('.1')
    assert not leg['funding_complete']
    with sessions() as db:
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'estimated_funding_gap')) == 1


@pytest.mark.asyncio
async def test_no_funding_gap_after_known_position_already_closed(omni_context):
    service, _, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    node = omni.node
    clock[0] = node - 1000
    await service.sync_leg(leg_id, clock[0])
    clock[0] = node + 1000
    await service.save_manual(card_id, leg_id, position(1, '0', close_price='100', confirm_closed=True))
    clock[0] = node + 3 * INTERVAL + 1000
    omni.node = node + 4 * INTERVAL
    await service.sync_leg(leg_id, clock[0])
    assert view(omni_context, card_id)['legs'][1]['funding_complete']


@pytest.mark.asyncio
async def test_interval_change_is_explicit(omni_context):
    service, _, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    clock[0] = omni.node + 1000
    omni.interval //= 2
    omni.node += INTERVAL // 2
    await service.sync_leg(leg_id, clock[0])
    assert not view(omni_context, card_id)['legs'][1]['funding_complete']


@pytest.mark.asyncio
async def test_zero_funding_rate_is_available():
    listing = public_listing()
    listing['funding']['last'] = dict(interval_rate='0', annualized_rate='0')
    adapter = Omni(httpx.MockTransport(lambda _: httpx.Response(200, json=dict(listings=[listing]))))
    snap = await adapter.fetch_market_snapshot('BTC-PERP')
    assert snap['rate'] == '0' and snap['daily_rate'] == '0'
    await adapter.close()


@pytest.mark.asyncio
async def test_funding_event_checkpoint_and_snapshot_commit_together(omni_context):
    service, sessions, _, omni, _, clock = omni_context
    card_id, leg_id, _ = await new_omni(omni_context)
    clock[0] += 1000
    await service.save_manual(card_id, leg_id, position(0, '1', '100'))
    node = omni.node
    clock[0] = node - 1000
    await service.sync_leg(leg_id, clock[0])
    clock[0] = node + 1000
    omni.node += INTERVAL
    engine = sessions.kw['bind']
    def fail_snapshot(connection, cursor, statement, parameters, context, many):
        if statement.startswith('INSERT INTO snapshots'):
            raise RuntimeError('simulated database failure')
    sql_event.listen(engine, 'before_cursor_execute', fail_snapshot)
    try:
        with pytest.raises(RuntimeError, match='database failure'):
            await service.sync_leg(leg_id, clock[0])
    finally:
        sql_event.remove(engine, 'before_cursor_execute', fail_snapshot)
    with sessions() as db:
        assert db.get(Cursor, f'{leg_id}:estimated') is None
        assert db.scalar(select(func.count()).select_from(Event).where(Event.kind == 'estimated_funding')) == 0
    await service.sync_leg(leg_id, clock[0])
    with sessions() as db:
        assert db.get(Card, card_id).revised_at == clock[0]
        assert db.get(Cursor, f'{leg_id}:estimated').through == node


@pytest.mark.asyncio
async def test_no_manual_entry_and_one_leg_closed_cannot_archive(omni_context):
    service, _, auto, _, _, clock = omni_context
    card_id, _, auto_id = await new_omni(omni_context)
    auto.fills = [fill(1, 'BUY', '1', '100'), fill(2, 'SELL', '1', '100')]
    for i, event in enumerate(auto.fills):
        event['time'] = BASE + i + 1
    for _ in range(2):
        clock[0] += 60000
        await service.sync_leg(auto_id, clock[0])
        service.reconcile(card_id, clock[0])
    assert view(omni_context, card_id)['status'] != 'archived'


def test_manual_api_auth_sources_and_request_validation(omni_context):
    service, sessions, _, _, settings, clock = omni_context
    app = create_app(settings, service.adapters, sessions, background=False)
    with TestClient(app) as client:
        body = dict(legs=[dict(account='binance', product='perp', symbol='BTCUSDT', direction='LONG'),
                          dict(account='omni', product='perp', symbol='BTC-PERP', direction='SHORT')])
        client.auth = ('admin', 'test-secret')
        card_id = client.post('/api/v1/cards', json=body).json()['id']
        card = client.get('/api/v1/cards').json()[0]
        leg_id = card['legs'][1]['id']
        route = f'/api/v1/cards/{card_id}/legs/{leg_id}/manual-position'
        clock[0] += 1000
        payload = position(0, '1', '100').model_dump(mode='json')
        assert client.post(route, json=payload, auth=('admin', 'wrong')).status_code == 401
        assert client.post(route, json=dict(payload, qty='NaN')).status_code == 422
        assert client.post(route, json=payload).status_code == 200
        assert client.post(route, json=payload).json()['revision'] == 1
        assert client.post(route, json=position(0, '2', '100').model_dump(mode='json')).status_code == 409
        events = client.get(f'/api/v1/cards/{card_id}/events').json()
        assert len(events) == 1 and events[0]['source'] == 'manual'
        accounts = client.get('/api/v1/accounts').json()
        assert accounts['accounts'][1]['quote_asset'] == 'USDC'
        assert accounts['execution_enabled'] is False
