from decimal import Decimal

D = Decimal
ZERO = D('0')


def calculate(events, direction, product, base, mark=None):
    """Replay immutable fills in exchange order; do not add income realized PnL twice."""
    qty = cost = realized = fees = funding = adjustments = opened = ZERO
    first = last = None
    issues = []
    fills = 0
    for event in sorted(events, key=lambda e: (e['time'], int(e['external_id']) if e['external_id'].isdigit() else 0)):
        row = event['data']
        if event['kind'] == 'income':
            if row['type'] == 'FUNDING_FEE':
                if row['asset'] == 'USDT':
                    funding += D(row['amount'])
                else:
                    issues.append('非 USDT 资金费待估值')
            elif row['type'] in ('INSURANCE_CLEAR', 'COMMISSION_REBATE', 'API_REBATE', 'MARKET_MAKER_REBATE'):
                if row['asset'] == 'USDT':
                    adjustments += D(row['amount'])
                else:
                    issues.append('非 USDT 费用待估值')
            continue
        fills += 1
        first = event['time'] if first is None else first
        last = event['time']
        amount, price, fee = D(row['qty']), D(row['price']), D(row['fee'])
        fee_value = row.get('fee_usdt')
        if fee_value is None:
            issues.append('手续费待估值')
        else:
            fees += D(fee_value)
        opening = row['side'] == ('BUY' if direction == 'LONG' else 'SELL')
        base_fee = fee if product == 'spot' and row['fee_asset'] == base else ZERO
        if opening:
            received = amount - base_fee
            if received <= 0:
                issues.append('成交净数量异常')
                continue
            qty += received
            # Base-asset fees are expensed separately, not capitalized twice.
            cost += received * price
            opened += amount * price
        else:
            reduction = amount + base_fee
            if reduction > qty:
                issues.append('减仓超出归属数量或出现反转仓位')
                continue
            average = cost / qty if qty else ZERO
            realized += (price - average) * reduction * (1 if direction == 'LONG' else -1)
            qty -= reduction
            cost = average * qty
    average = cost / qty if qty else ZERO
    unrealized = None if mark is None else qty * (D(mark) - average) * (1 if direction == 'LONG' else -1)
    return dict(qty=str(qty), average=str(average), realized=str(realized), fees=str(fees), funding=str(funding), adjustments=str(adjustments),
                net=str(realized + funding + adjustments - fees), opened=str(opened), unrealized=None if unrealized is None else str(unrealized),
                first=first, last=last, fills=fills, issues=sorted(set(issues)))


def summary(legs, at):
    net = sum((D(x['net']) for x in legs), ZERO)
    opened = sum((D(x['opened']) for x in legs), ZERO)
    first = min((x['first'] for x in legs if x['first'] is not None), default=None)
    duration = at - first if first is not None else 0
    valid = not any(x['issues'] for x in legs)
    annual = net / opened * D(365 * 86400000) / duration if opened and duration > 0 and valid else None
    qty = [D(x['qty']) for x in legs]
    imbalance = abs(qty[0] - qty[1]) / max(qty) if max(qty, default=ZERO) else ZERO
    floating = sum((D(x['unrealized']) for x in legs), ZERO) if all(x['unrealized'] is not None for x in legs) else None
    return dict(net=str(net), opened=str(opened), annual=None if annual is None else str(annual),
                total=None if floating is None else str(net + floating), imbalance=str(imbalance), complete=valid)


def manual_records(events):
    """Corrections supersede the latest position, without deleting the original evidence."""
    records = [e for e in events if e['kind'] == 'manual_position']
    replaced = {e['data'].get('replaces') for e in records}
    return sorted((e for e in records if e['external_id'] not in replaced),
                  key=lambda e: (e['time'], e['data']['revision']))


def manual_quantity_at(records, at):
    before = [e for e in records if e['time'] <= at]
    return D(before[-1]['data']['qty']) if before else None


def manual_exposed(records, start, end):
    return bool(manual_quantity_at(records, start)) or any(
        start < e['time'] <= end and D(e['data']['qty']) > 0 for e in records)


def manual_funding_amount(records, data, direction):
    qty = manual_quantity_at(records, data['settlement_time'])
    return None if qty is None else qty * D(data['mark']) * D(data['rate']) * (1 if direction == 'SHORT' else -1)


def calculate_manual(events, direction, mark=None):
    records = manual_records(events)
    qty = average = realized = opened = fees = funding = ZERO
    first = last = None
    fills = 0
    for event in records:
        row = event['data']
        new_qty = D(row['qty'])
        new_average = D(row['average'])
        fees += D(row['fee'])
        if new_qty > qty:
            opened += new_qty * new_average - qty * average
            first = event['time'] if first is None else first
        elif new_qty < qty:
            realized += (D(row['close_price']) - average) * (qty - new_qty) * (1 if direction == 'LONG' else -1)
        if new_qty != qty:
            fills += 1
            last = event['time']
        qty, average = new_qty, new_average
    issues = [] if records else ['Omni 仓位待手工录入']
    estimates = {}
    for event in events:
        row = event['data']
        if event['kind'] == 'estimated_funding':
            amount = manual_funding_amount(records, row, direction)
            estimates[event['external_id']] = None if amount is None else str(amount)
            if amount is None:
                issues.append('Omni 结算时仓位未知')
            else:
                funding += amount
        elif event['kind'] == 'estimated_funding_gap' and manual_exposed(records, row['start'], row['end']):
            issues.append('Omni 资金费存在漏采区间，历史无法补造')
    unrealized = None if not records else ZERO if qty == 0 else None if mark is None else qty * (D(mark) - average) * (1 if direction == 'LONG' else -1)
    return dict(qty=str(qty), average=str(average), realized=str(realized), fees=str(fees), funding='0',
        adjustments='0', net=str(realized - fees), opened=str(opened),
        unrealized=None if unrealized is None else str(unrealized), first=first, last=last, fills=fills,
        issues=sorted(set(issues)), estimated_funding=str(funding), funding_complete=not any('资金费' in i or '结算' in i for i in issues),
        funding_estimates=estimates, manual_entered=bool(records),
        last_manual=dict(records[-1]['data'], time=records[-1]['time'],
            previous_qty=records[-2]['data']['qty'] if len(records) > 1 else '0',
            previous_average=records[-2]['data']['average'] if len(records) > 1 else '0') if records else None,
        closed_confirmed=bool(records and qty == 0 and records[-1]['data']['confirm_closed']),
        manual_updated_at=max((e['data']['recorded_at'] for e in events if e['kind'] == 'manual_position'), default=None))
