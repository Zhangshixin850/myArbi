import asyncio
import logging
from decimal import Decimal as D

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from .adapters import DAY, ExchangeError
from .ledger import calculate, summary
from .models import Audit, Card, Cursor, Event, Leg, Snapshot, now_ms

log = logging.getLogger('arbi')


def events_for(db, leg):
    return [dict(kind=e.kind, external_id=e.external_id, time=e.time, data=e.data) for e in
            db.scalars(select(Event).where(Event.leg_id == leg.id).order_by(Event.time, Event.id))]


def leg_view(db, leg, base):
    result = calculate(events_for(db, leg), leg.direction, leg.product, base, leg.snapshot.get('mark'))
    return dict(id=leg.id, account=leg.account, product=leg.product, symbol=leg.symbol, direction=leg.direction,
                synced_at=leg.synced_at, error=leg.error, snapshot=leg.snapshot, **result)


def card_view(db, card, settings):
    legs = [leg_view(db, leg, card.base) for leg in card.legs]
    result = summary(legs, card.closed_at or now_ms())
    alerts = []
    for leg in legs:
        alerts.extend(leg['issues'])
        if leg['error']:
            alerts.append(leg['account'] + ': ' + leg['error'])
        if card.status not in ('archived', 'cancelled') and (not leg['synced_at'] or now_ms() - leg['synced_at'] > settings.stale_seconds * 1000):
            alerts.append(leg['account'] + ': 数据过期')
        snap = leg['snapshot']
        if leg['product'] == 'perp' and D(leg['qty']) and snap.get('equity') is not None and D(snap['equity']) <= 0:
            alerts.append(leg['account'] + ': 账户权益非正')
        for field, threshold, label in [('leverage', settings.max_leverage, '账户杠杆过高'), ('margin_usage', settings.max_margin_usage, '保证金风险过高')]:
            if snap.get(field) is not None and D(snap[field]) >= threshold:
                alerts.append(leg['account'] + ': ' + label)
        if snap.get('liquidation_distance') is not None and D(snap['liquidation_distance']) <= settings.min_liquidation_distance:
            alerts.append(leg['account'] + ': 接近强平价格')
        if snap.get('adl') is not None and snap['adl'] >= 3:
            alerts.append(leg['account'] + ': ADL 风险较高')
    if D(result['imbalance']) > settings.imbalance_ratio:
        alerts.append('双腿数量不平衡')
    return dict(id=card.id, base=card.base, status=card.status, started_at=card.started_at, closed_at=card.closed_at,
                revised_at=card.revised_at, legs=legs, alerts=sorted(set(alerts)), **result)


def position_for(account, symbol, direction):
    return next((p for p in account['positions'] if p['symbol'] == symbol and
                 p.get('positionSide', 'BOTH') in ('BOTH', direction)), {})


class Service:
    def __init__(self, sessions, adapters, settings):
        self.sessions, self.adapters, self.settings = sessions, adapters, settings
        self.lock = asyncio.Lock()
        self.backoff = {}

    async def create_card(self, specs):
        async with self.lock:
            legs = []
            bases = []
            for spec in specs:
                adapter = self.adapters.get((spec.account, spec.product))
                if adapter is None:
                    raise ValueError('账户未配置或产品不受支持')
                await adapter.fetch_markets()
                market = adapter.markets.get(spec.symbol)
                if market is None:
                    raise ValueError('不支持的 USDT 市场')
                if spec.product == 'spot' and spec.direction != 'LONG':
                    raise ValueError('现货只支持多头')
                # Baselines always bypass account cache.
                adapter.cache.clear()
                account = await adapter.fetch_account_risk()
                position = position_for(account, spec.symbol, spec.direction)
                if D(position.get('positionAmt', '0')) != 0:
                    raise ValueError('对应永续方向已有仓位，请从空仓开始')
                bases.append(market['base'])
                legs.append(Leg(account=spec.account, product=spec.product, symbol=spec.symbol, direction=spec.direction,
                    reservation=spec.direction if account['mode'] == 'HEDGE' else 'BOTH',
                    baseline=dict(balance=account['balances'].get(market['base'], '0'), equity=account['equity'], mode=account['mode'], step=market['step'])))
            if len(set(bases)) != 1 or specs[0].account == specs[1].account or specs[0].direction == specs[1].direction:
                raise ValueError('双腿必须为同一基础币、不同平台和相反方向')
            with self.sessions.begin() as db:
                for leg in legs:
                    existing = list(db.scalars(select(Leg).where(Leg.account == leg.account, Leg.product == leg.product,
                        Leg.symbol == leg.symbol, Leg.reserved.is_(True))))
                    if any(x.reservation == 'BOTH' or leg.reservation == 'BOTH' or x.direction == leg.direction for x in existing):
                        raise ValueError('该账户合约方向已被活跃卡片占用')
                    # Income has no reliable position-side tag on these APIs.
                    if existing:
                        raise ValueError('同合约双向资金费无法可靠拆分，首版请使用独立账户')
                card = Card(base=bases[0], legs=legs, started_at=now_ms())
                db.add(card)
                db.flush()
                db.add(Audit(card_id=card.id, message='创建卡片并记录账户基线'))
                return card.id

    async def sync_leg(self, leg_id, until):
        with self.sessions() as db:
            leg = db.get(Leg, leg_id)
            card = db.get(Card, leg.card_id)
            adapter = self.adapters[(leg.account, leg.product)]
            await adapter.fetch_markets()
            archived = card.status == 'archived'
            boundary = min(until, card.closed_at) if archived else until
            # Audit the complete strategy daily; hot polls overlap by 5 minutes.
            cursor = db.get(Cursor, f'{leg_id}:fills')
            audit = not cursor or until - cursor.audited_at >= DAY
            if not archived and until - (cursor.through if cursor else card.started_at) > 90 * DAY:
                raise ExchangeError('缺口超过首版 90 天补查范围，需人工核对')
            start = max(card.started_at, until - 90 * DAY) if audit else max(card.started_at, cursor.through - 300000)
            fills = await adapter.fetch_fills(leg.symbol, start, boundary) if start <= boundary else []
            funding_cursor = db.get(Cursor, f'{leg_id}:income')
            funding_start = max(card.started_at, until - 90 * DAY) if audit or not funding_cursor else max(card.started_at, funding_cursor.through - DAY)
            income = await adapter.fetch_funding_payments(leg.symbol, funding_start, boundary) if funding_start <= boundary else []
            # Signed commission cash flows disambiguate Aster's fee/rebate convention.
            if leg.account == 'aster':
                commissions = {}
                for item in income:
                    trade_id = str(item['raw'].get('tradeId', ''))
                    if item['data']['type'] == 'COMMISSION' and trade_id:
                        key = (trade_id, item['data']['asset'])
                        commissions[key] = commissions.get(key, D(0)) - D(item['data']['amount'])
                for item in fills:
                    key = (item['external_id'], item['data']['fee_asset'])
                    if key in commissions:
                        item['data']['fee'] = str(commissions[key])
                        item['data']['fee_usdt'] = str(commissions[key]) if key[1] == 'USDT' else None
                    elif D(item['data']['fee']) != 0:
                        item['data']['fee_usdt'] = None
            account = None if archived else await adapter.fetch_account_risk()
            market = {} if archived else await adapter.fetch_market_snapshot(leg.symbol)
            base, direction, product = card.base, leg.direction, leg.product
            card_id = card.id
        with self.sessions.begin() as db:
            leg = db.get(Leg, leg_id)
            card = db.get(Card, card_id)
            changed = False
            for item in fills + income:
                if not card.started_at <= item['time'] <= boundary:
                    continue
                if item['kind'] == 'fill' and item['data']['position_side'] not in ('BOTH', direction):
                    continue
                row = dict(leg_id=leg.id, account=leg.account, product=product, symbol=leg.symbol, **item)
                inserted = db.execute(insert(Event).values(**row).on_conflict_do_nothing())
                changed |= inserted.rowcount > 0
                # Retry previously unavailable fee conversion without altering raw evidence.
                if item['kind'] == 'fill' and item['data'].get('fee_usdt') is not None:
                    old = db.scalar(select(Event).where(Event.leg_id == leg.id, Event.kind == 'fill', Event.external_id == item['external_id']))
                    if old and old.data.get('fee_usdt') is None:
                        old.data = item['data']
                        changed = True
            for kind in ('fills', 'income'):
                key = f'{leg_id}:{kind}'
                current = db.get(Cursor, key)
                if current is None:
                    current = Cursor(key=key, through=boundary, audited_at=until)
                    db.add(current)
                else:
                    current.through = boundary
                    if audit:
                        current.audited_at = until
            db.flush()
            totals = calculate(events_for(db, leg), direction, product, base, market.get('mark'))
            error = None
            if account is not None:
                position = position_for(account, leg.symbol, direction)
                actual = D(account['balances'].get(base, '0')) - D(leg.baseline['balance']) if product == 'spot' else abs(D(position.get('positionAmt', '0')))
                # Dust is displayed, never silently treated as a closed position.
                if actual != D(totals['qty']):
                    error = '账户数量与归属账本不符，请核对成交、转账或反转仓位'
                signed = D(position.get('positionAmt', '0'))
                if product != 'spot' and ((direction == 'SHORT' and signed > 0) or (direction == 'LONG' and signed < 0)):
                    error = '实际持仓方向与卡片相反'
                if product != 'spot' and leg.baseline['mode'] != account['mode']:
                    error = '持仓模式发生变化，需要核对'
                liquidation = D(position.get('liquidationPrice', '0'))
                mark = D(market['mark'])
                adl = next((r.get('adlQuantile', {}).get(direction if account['mode'] == 'HEDGE' else 'BOTH')
                            for r in account['adl'] if r['symbol'] == leg.symbol), None)
                leg.snapshot = dict(**market, actual_qty=str(actual), equity=account['equity'], leverage=account['leverage'],
                    margin_usage=account['margin_usage'], liquidation_price=str(liquidation) if liquidation else None,
                    liquidation_distance=str(abs(mark - liquidation) / mark) if liquidation and mark else None, adl=adl)
                db.add(Snapshot(leg_id=leg.id, time=until, data=leg.snapshot))
            leg.error = error or ('；'.join(totals['issues']) if totals['issues'] else None)
            leg.synced_at = until
            if changed:
                card.revised_at = until
                db.add(Audit(card_id=card.id, message='同步新流水或修订估值' + ('（归档后）' if archived else '')))

    def reconcile(self, card_id, until):
        with self.sessions.begin() as db:
            card = db.get(Card, card_id)
            if card.status not in ('active', 'reconciling'):
                return
            legs = [leg_view(db, leg, card.base) for leg in card.legs]
            healthy = all(x['synced_at'] == until and not x['error'] and not x['issues'] for x in legs)
            traded = all(x['fills'] > 0 for x in legs)
            zero = all(D(x['qty']) == 0 for x in legs)
            if healthy and traded and zero:
                if card.zero_since is not None and until - card.zero_since >= self.settings.poll_seconds * 1000:
                    card.status = 'archived'
                    card.closed_at = max(x['last'] for x in legs)
                    card.revised_at = until
                    for leg in card.legs:
                        leg.reserved = False
                    db.add(Audit(card_id=card.id, message='连续两次同步验证双腿归零，自动归档'))
                else:
                    card.zero_since = until
                    card.status = 'reconciling'
            else:
                card.zero_since = None
                card.status = 'active' if healthy else 'reconciling'

    async def sync_once(self):
        async with self.lock:
            until = now_ms()
            with self.sessions() as db:
                cards = list(db.scalars(select(Card).where(Card.status != 'cancelled')))
                groups = {}
                ids = []
                for card in cards:
                    ids.append(card.id)
                    for leg in card.legs:
                        # Archived cards receive a daily complete income audit for 90 days.
                        if card.status == 'archived' and (until - card.closed_at > 90 * DAY or leg.synced_at and until - leg.synced_at < DAY):
                            continue
                        groups.setdefault(leg.account, []).append(leg.id)

            async def run_account(account, leg_ids):
                if until < self.backoff.get(account, 0):
                    return
                for adapter_key, adapter in self.adapters.items():
                    if adapter_key[0] == account:
                        adapter.cache.clear()
                for leg_id in leg_ids:
                    try:
                        await self.sync_leg(leg_id, until)
                    except Exception as exc:
                        message = str(exc) if isinstance(exc, ExchangeError) else '同步异常，请检查服务日志中的错误类型'
                        log.warning('sync_failed account=%s error_type=%s', account, type(exc).__name__)
                        self.backoff[account] = until + getattr(exc, 'retry_after', 300) * 1000
                        with self.sessions.begin() as db:
                            leg = db.get(Leg, leg_id)
                            leg.error = message
                        break
            await asyncio.gather(*(run_account(account, ids) for account, ids in groups.items()))
            for card_id in ids:
                self.reconcile(card_id, until)
            with self.sessions.begin() as db:
                db.execute(delete(Snapshot).where(Snapshot.time < until - self.settings.snapshot_retention_days * DAY))

    async def run(self):
        while True:
            try:
                await self.sync_once()
            except Exception as exc:
                log.error('scheduler_failed error_type=%s', type(exc).__name__)
            await asyncio.sleep(self.settings.poll_seconds)
