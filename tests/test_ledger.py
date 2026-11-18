from decimal import Decimal as D
from backend.ledger import calculate, summary


def fill(i, side, qty, price, fee='0', asset='USDT', value='0'):
    return dict(kind='fill', external_id=str(i), time=i * 1000, data=dict(side=side, qty=qty, price=price, fee=fee,
                fee_asset=asset, fee_usdt=value, position_side='BOTH'))


def test_weighted_partial_close_and_reopen():
    rows = [fill(1,'BUY','2','100'), fill(2,'BUY','1','130'), fill(3,'SELL','1','140'), fill(4,'BUY','1','120'), fill(5,'SELL','3','130')]
    result = calculate(list(reversed(rows)), 'LONG', 'perp', 'BTC', '130')
    assert D(result['qty']) == 0
    assert D(result['realized']).quantize(D('.01')) == 80
    assert D(result['opened']) == 450


def test_base_fee_not_double_counted():
    rows = [fill(1,'BUY','1','100','.01','BTC','1'), fill(2,'SELL','.99','110','1','USDT','1')]
    result = calculate(rows,'LONG','spot','BTC','110')
    assert D(result['qty']) == 0
    assert D(result['net']) == D('7.90')


def test_sell_base_fee_reduces_inventory():
    rows = [fill(1,'BUY','1','100'),fill(2,'SELL','.99','110','.01','BTC','1.1')]
    result = calculate(rows,'LONG','spot','BTC')
    assert D(result['qty']) == 0
    assert D(result['net']) == D('8.9')


def test_short_funding_and_income_not_double_counted():
    rows = [fill(1,'SELL','2','120','1','USDT','1'),fill(2,'BUY','2','100','1','USDT','1')]
    rows += [dict(kind='income',external_id='FUNDING_FEE:1',time=1500,data=dict(type='FUNDING_FEE',amount='3',asset='USDT')),
             dict(kind='income',external_id='REALIZED_PNL:2',time=2000,data=dict(type='REALIZED_PNL',amount='40',asset='USDT'))]
    result = calculate(rows,'SHORT','perp','BTC')
    assert D(result['net']) == 41


def test_missing_fee_and_reversal_block_complete_return():
    result = calculate([fill(1,'BUY','1','10','1','BNB',None),fill(2,'SELL','2','20')],'LONG','perp','BTC')
    assert len(result['issues']) == 2
    assert summary([result,result],5000)['annual'] is None


def test_annual_uses_cumulative_open_not_remaining():
    result = calculate([fill(1,'BUY','2','100'),fill(2,'SELL','1','110')],'LONG','perp','BTC','110')
    value = summary([result,result],1000+365*86400000)
    assert D(value['annual']) == D('.05')


def test_rebate_and_liquidation_cost_not_labeled_as_funding():
    rows = [dict(kind='income',external_id='INSURANCE_CLEAR:1',time=1000,
                 data=dict(type='INSURANCE_CLEAR',amount='-2',asset='USDT'))]
    result = calculate(rows,'LONG','perp','BTC')
    assert D(result['funding']) == 0
    assert D(result['adjustments']) == -2
    assert D(result['net']) == -2
