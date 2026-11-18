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
