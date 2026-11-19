import asyncio
import hashlib
import hmac
import re
import time
from collections import deque
from decimal import Decimal as D
from urllib.parse import urlencode

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

DAY = 86400000


class ExchangeError(Exception):
    """Safe message only: never include request URLs, signatures or response bodies."""

    def __init__(self, message, retry_after=300):
        super().__init__(message)
        self.retry_after = retry_after


class Exchange:
    def __init__(self, platform, product, settings, transport=None):
        self.platform, self.product, self.settings = platform, product, settings
        self.spot = product == 'spot'
        self.prefix = '/api/v3' if self.spot else '/fapi/v3' if platform == 'aster' else '/fapi/v1'
        host = 'https://api.binance.com' if self.spot else 'https://fapi.asterdex.com' if platform == 'aster' else 'https://fapi.binance.com'
        self.client = httpx.AsyncClient(base_url=host, timeout=15, transport=transport)
        self.lock = asyncio.Lock()
        self.nonce = 0
        self.offset = 0
        self.clock_checked = 0
        self.markets = {}
        self.cache = {}
        self.weights = deque()

    async def get(self, path, params=None, private=False):
        async with self.lock:
            for attempt in range(3):
                weight = 30 if path.endswith(('/income', '/incomePage')) else 20
                current = time.monotonic()
                while self.weights and current - self.weights[0][0] >= 60:
                    self.weights.popleft()
                if sum(w for _, w in self.weights) + weight > 900:
                    await asyncio.sleep(max(0, 60 - (current - self.weights[0][0])))
                    current = time.monotonic()
                    while self.weights and current - self.weights[0][0] >= 60:
                        self.weights.popleft()
                self.weights.append((time.monotonic(), weight))
                values = dict(params or {})
                headers = {}
                if private:
                    if time.monotonic() - self.clock_checked > 300:
                        try:
                            clock = await self.client.get(self.prefix + '/time')
                            self.offset = int(clock.json()['serverTime']) - time.time_ns() // 1_000_000
                            self.clock_checked = time.monotonic()
                        except Exception:
                            raise ExchangeError('平台时间同步失败') from None
                    if self.platform == 'binance':
                        values.update(timestamp=time.time_ns() // 1_000_000 + self.offset, recvWindow=5000)
                        query = urlencode(values)
                        signature = hmac.new(self.settings.binance_api_secret.get_secret_value().encode(), query.encode(), hashlib.sha256).hexdigest()
                        headers['X-MBX-APIKEY'] = self.settings.binance_api_key.get_secret_value()
                    else:
                        self.nonce = max(self.nonce + 1, time.time_ns() // 1000 + self.offset * 1000)
                        values.update(user=self.settings.aster_user, signer=self.settings.aster_signer, nonce=str(self.nonce))
                        query = urlencode(values)
                        message = encode_typed_data(domain_data={'name': 'AsterSignTransaction', 'version': '1', 'chainId': 1666,
                            'verifyingContract': '0x0000000000000000000000000000000000000000'},
                            message_types={'Message': [{'name': 'msg', 'type': 'string'}]}, message_data={'msg': query})
                        signature = '0x' + Account.sign_message(message, self.settings.aster_private_key.get_secret_value()).signature.hex().removeprefix('0x')
                    query += '&signature=' + signature
                else:
                    query = urlencode(values)
                try:
                    response = await self.client.get(path + ('?' + query if query else ''), headers=headers)
                    if response.status_code in (418, 429):
                        # Respect server cooldown; the outer account loop also backs off.
                        try:
                            cooldown = max(300, int(response.headers.get('Retry-After', '300')))
                        except ValueError:
                            cooldown = 300
                        raise ExchangeError('平台限流，暂停该账户同步', cooldown)
                    if response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise ExchangeError('平台服务暂不可用')
                    if response.status_code >= 400:
                        raise ExchangeError('平台认证或请求失败，HTTP ' + str(response.status_code))
                    data = response.json()
                    if isinstance(data, dict) and isinstance(data.get('code'), int) and data['code'] < 0:
                        raise ExchangeError('平台错误码 ' + str(data['code']))
                    await asyncio.sleep(.15)
                    return data
                except httpx.HTTPError:
                    if attempt == 2:
                        raise ExchangeError('平台网络连接失败') from None
                    await asyncio.sleep(2 ** attempt)

    async def fetch_markets(self):
        if not self.markets:
            data = await self.get(self.prefix + '/exchangeInfo')
            for row in data['symbols']:
                if row.get('status') != 'TRADING' or row.get('quoteAsset') != 'USDT':
                    continue
                if not self.spot and (row.get('contractType') != 'PERPETUAL' or row.get('marginAsset') != 'USDT'):
                    continue
                if self.spot and not row.get('isSpotTradingAllowed', True):
                    continue
                step = next((x['stepSize'] for x in row['filters'] if x['filterType'] == 'LOT_SIZE'), '0.00000001')
                self.markets[row['symbol']] = dict(symbol=row['symbol'], base=row['baseAsset'], quote='USDT', step=step)
        return list(self.markets.values())

    async def window_rows(self, path, symbol, start, end):
        """Split full time windows instead of dropping records sharing a timestamp."""
        rows = await self.get(path, dict(symbol=symbol, startTime=start, endTime=end, limit=1000), True)
        if not isinstance(rows, list):
            raise ExchangeError('平台历史数据格式异常')
        if len(rows) < 1000:
            return rows
        if start == end:
            raise ExchangeError('单毫秒历史超出接口上限，账本需要人工核对')
        mid = (start + end) // 2
        return await self.window_rows(path, symbol, start, mid) + await self.window_rows(path, symbol, mid + 1, end)

    async def fetch_fills(self, symbol, start, end):
        result = []
        path = self.prefix + ('/myTrades' if self.spot else '/userTrades')
        # Both exchanges accept these bounded windows; spot requires <=24h.
        while start <= end:
            until = min(end, start + DAY - 1)
            result.extend(await self.window_rows(path, symbol, start, until))
            start = until + 1
        events = []
        base = self.markets[symbol]['base']
        for row in result:
            fee = D(row['commission'])
            # Aster V3 reports commission as signed cash flow; Binance reports expense.
            if self.platform == 'aster':
                fee = -fee
            asset = row['commissionAsset']
            fee_usdt = str(fee) if asset == 'USDT' else str(fee * D(row['price'])) if asset == base else None
            if fee == 0:
                fee_usdt = '0'
            if fee_usdt is None:
                try:
                    k = await self.get(self.prefix + '/klines', dict(symbol=asset + 'USDT', interval='1m',
                        startTime=int(row['time']) // 60000 * 60000, limit=1))
                    if k and int(k[0][0]) == int(row['time']) // 60000 * 60000:
                        fee_usdt = str(fee * D(k[0][4]))
                except ExchangeError:
                    pass
            events.append(dict(kind='fill', external_id=str(row['id']), time=int(row['time']), raw=row,
                data=dict(qty=row['qty'], price=row['price'], fee=str(fee), fee_asset=asset, fee_usdt=fee_usdt,
                    side=row.get('side') or ('BUY' if row['isBuyer'] else 'SELL'), position_side=row.get('positionSide', 'BOTH'))))
        return events

    async def fetch_funding_payments(self, symbol, start, end):
        if self.spot:
            return []
        result = []
        while start <= end:
            until = min(end, start + 7 * DAY - 1)
            page = 1
            while True:
                path = self.prefix + ('/incomePage' if self.platform == 'aster' else '/income')
                data = await self.get(path, dict(symbol=symbol, startTime=start, endTime=until, page=page, limit=1000), True)
                rows = data['rows'] if self.platform == 'aster' else data
                result.extend(rows)
                more = data['hasMore'] if self.platform == 'aster' else len(rows) == 1000
                if not more:
                    break
                page += 1
                if page > 100:
                    raise ExchangeError('资金流水分页上限，尚未完成同步')
            start = until + 1
        return [dict(kind='income', external_id=str(r['incomeType']) + ':' + str(r['tranId']), time=int(r['time']), raw=r,
                     data=dict(type=r['incomeType'], amount=r['income'], asset=r['asset'])) for r in result]

    async def fetch_account_risk(self):
        cached = self.cache.get('account')
        if cached and time.monotonic() - cached[0] < 10:
            return cached[1]
        if self.spot:
            account = await self.get(self.prefix + '/account', private=True)
            result = dict(balances={r['asset']: str(D(r['free']) + D(r['locked'])) for r in account['balances']},
                          positions=[], mode='BOTH', equity=None, leverage=None, margin_usage=None, adl=[])
        else:
            account_path = '/fapi/v3/account'
            account = await self.get(account_path, private=True)
            if account.get('multiAssetsMargin') is True:
                raise ExchangeError('首版不支持多资产保证金模式')
            mode = await self.get(self.prefix + '/positionSide/dual', private=True)
            positions = await self.get('/fapi/v3/positionRisk', private=True)
            if not isinstance(positions, list):
                raise ExchangeError('仓位数据格式异常')
            equity = D(account['totalMarginBalance'])
            nominal = sum((abs(D(r.get('notional', '0'))) for r in positions), D(0))
            adl = []
            try:
                adl = await self.get(self.prefix + '/adlQuantile', private=True)
            except ExchangeError:
                pass
            result = dict(positions=positions, mode='HEDGE' if mode['dualSidePosition'] else 'BOTH', equity=str(equity),
                leverage=str(nominal / equity) if equity > 0 else None,
                margin_usage=str(D(account['totalMaintMargin']) / equity) if equity > 0 else None, adl=adl, balances={})
        self.cache['account'] = (time.monotonic(), result)
        return result

    async def fetch_positions(self):
        return (await self.fetch_account_risk())['positions']

    async def fetch_market_snapshot(self, symbol):
        if self.spot:
            price = await self.get(self.prefix + '/ticker/price', dict(symbol=symbol))
            return dict(mark=price['price'], rate=None, next_funding=None, interval_hours=None, daily_rate=None)
        data = await self.get(self.prefix + '/premiumIndex', dict(symbol=symbol))
        history = await self.get(self.prefix + '/fundingRate', dict(symbol=symbol, limit=2))
        interval = None
        if len(history) == 2:
            interval = D(str(history[1]['fundingTime'] - history[0]['fundingTime'])) / 3600000
        return dict(mark=data['markPrice'], rate=data.get('lastFundingRate'), next_funding=data.get('nextFundingTime'),
            interval_hours=str(interval) if interval else None,
            daily_rate=str(D(data['lastFundingRate']) * 24 / interval) if interval and data.get('lastFundingRate') else None,
            interval_source='最近两次结算间隔')

    async def close(self):
        await self.client.aclose()


class Omni:
    """Official public v2 statistics only; never fetch private account endpoints."""

    def __init__(self, transport=None):
        self.client = httpx.AsyncClient(
            base_url='https://omni-client-api.prod.ap-northeast-1.variational.io',
            timeout=15, transport=transport)
        self.lock = asyncio.Lock()
        self.markets = {}
        self.cache = {}
        self.retry_at = 0

    async def stats(self):
        async with self.lock:
            current = time.monotonic()
            if current < self.retry_at:
                raise ExchangeError('Omni 公开接口限流，请稍后重试', max(1, int(self.retry_at - current) + 1))
            cached = self.cache.get('stats')
            if cached and current - cached[0] < 10:
                return cached[1], cached[2]
            try:
                response = await self.client.get('/metadata/v2/stats')
                if response.status_code == 429:
                    try:
                        delay = max(10, min(3600, int(response.json().get('retry_after_seconds', 10))))
                    except (ValueError, TypeError, AttributeError):
                        delay = 10
                    self.retry_at = time.monotonic() + delay
                    raise ExchangeError('Omni 公开接口限流，请稍后重试', delay)
                if response.status_code != 200:
                    raise ExchangeError('Omni 公开接口失败，HTTP ' + str(response.status_code), 30)
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get('listings'), list):
                    raise ValueError()
            except httpx.HTTPError:
                raise ExchangeError('Omni 公开接口网络连接失败', 30) from None
            except (ValueError, TypeError):
                raise ExchangeError('Omni 公开数据格式异常', 30) from None
            observed = time.time_ns() // 1_000_000
            self.cache['stats'] = (time.monotonic(), data, observed)
            self.markets = {
                row['ticker']: dict(symbol=row['ticker'], base=row['ticker'][:-5], quote='USDC',
                                    step=None, source='manual')
                for row in data['listings'] if isinstance(row, dict) and row.get('contract_type') == 'perpetual'
                and isinstance(row.get('ticker'), str) and re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,39}-PERP', row['ticker'])
            }
            return data, observed

    async def fetch_markets(self):
        await self.stats()
        return list(self.markets.values())

    async def fetch_market_snapshot(self, symbol):
        data, observed = await self.stats()
        row = next((r for r in data['listings'] if isinstance(r, dict) and r.get('ticker') == symbol
                    and r.get('contract_type') == 'perpetual'), None)
        if row is None:
            raise ExchangeError('Omni 永续市场不可用或已下架', 30)
        try:
            mark = D(row['mark_price'])
            if not mark.is_finite() or mark <= 0:
                raise ValueError()
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise ExchangeError('Omni 标记价格不可用', 30) from None
        result = dict(mark=str(mark), rate=None, annualized_rate=None, next_funding=None,
            interval_hours=None, interval_seconds=None, daily_rate=None, observed_at=observed,
            quote_asset='USDC', equity=None, leverage=None, margin_usage=None,
            liquidation_price=None, liquidation_distance=None, adl=None)
        funding = row.get('funding')
        if funding:
            try:
                interval = int(funding['interval_seconds'])
                next_time = int(funding['next_timestamp']) * 1000
                rates = funding.get('next') or funding['last']
                rate = D(rates['interval_rate'])
                annual = D(rates['annualized_rate'])
                if interval <= 0 or next_time <= observed or not rate.is_finite() or not annual.is_finite():
                    raise ValueError()
                result.update(rate=str(rate), annualized_rate=str(annual), next_funding=next_time,
                    interval_seconds=interval, interval_hours=str(D(interval) / 3600),
                    daily_rate=str(rate * D(86400) / interval))
            except (KeyError, ValueError, TypeError, ArithmeticError):
                # A price can be usable while funding terms are unavailable.
                pass
        return result

    async def close(self):
        await self.client.aclose()
