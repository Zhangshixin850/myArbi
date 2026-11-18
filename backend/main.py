import asyncio
import logging
import secrets
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .adapters import Exchange, ExchangeError
from .config import Settings
from .db import database
from .models import Audit, Card, Event
from .service import Service, card_view


class LegInput(BaseModel):
    account: Literal['binance', 'aster']
    product: Literal['spot', 'perp']
    symbol: str = Field(pattern=r'^[A-Z0-9]{3,30}$')
    direction: Literal['LONG', 'SHORT']


class CardInput(BaseModel):
    legs: list[LegInput] = Field(min_length=2, max_length=2)


class ExecutionIntent(BaseModel):
    card_id: str
    quantity: str
    spread: str
    action: Literal['open', 'close']
    mode: Literal['both_market', 'limit_then_market']


def create_app(settings=None, adapters=None, sessions=None, background=True):
    settings = settings or Settings()
    engine = None
    if sessions is None:
        engine, sessions = database(settings.database_url)
    if adapters is None:
        adapters = {}
        if settings.binance_api_key.get_secret_value() and settings.binance_api_secret.get_secret_value():
            for product in ('spot', 'perp'):
                adapters['binance', product] = Exchange('binance', product, settings)
        if settings.aster_user and settings.aster_signer and settings.aster_private_key.get_secret_value():
            adapters['aster', 'perp'] = Exchange('aster', 'perp', settings)
    service = Service(sessions, adapters, settings)

    @asynccontextmanager
    async def lifespan(app):
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)
        if not settings.app_password.get_secret_value():
            raise RuntimeError('Set APP_PASSWORD in .env before starting the server')
        task = asyncio.create_task(service.run()) if background else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for adapter in adapters.values():
            await adapter.close()
        if engine:
            engine.dispose()

    app = FastAPI(title='myArbi 记账', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    basic = HTTPBasic()

    def auth(credentials: HTTPBasicCredentials = Depends(basic)):
        valid_user = secrets.compare_digest(credentials.username.encode(), settings.app_user.encode())
        valid_pass = secrets.compare_digest(credentials.password.encode(), settings.app_password.get_secret_value().encode())
        if not valid_user or not valid_pass or not settings.app_password.get_secret_value():
            raise HTTPException(401, '登录失败', headers={'WWW-Authenticate': 'Basic'})

    guard = [Depends(auth)]

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}

    @app.get('/api/v1/accounts', dependencies=guard)
    def accounts():
        return {'accounts': [dict(id=a, product=p, execution_enabled=False) for a, p in adapters], 'execution_enabled': False}

    @app.get('/api/v1/markets', dependencies=guard)
    async def markets(account: str, product: str):
        adapter = adapters.get((account, product))
        if not adapter:
            raise HTTPException(400, '账户未配置')
        try:
            return await adapter.fetch_markets()
        except ExchangeError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.get('/api/v1/cards', dependencies=guard)
    def cards():
        with sessions() as db:
            return [card_view(db, card, settings) for card in db.scalars(select(Card).order_by(Card.started_at.desc()))]

    @app.post('/api/v1/cards', status_code=201, dependencies=guard)
    async def create(body: CardInput):
        try:
            return {'id': await service.create_card(body.legs)}
        except (ValueError, IntegrityError) as exc:
            raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else '卡片归属冲突') from None
        except ExchangeError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.get('/api/v1/cards/{card_id}/events', dependencies=guard)
    def events(card_id: str, offset: int = 0, limit: int = 200):
        if offset < 0 or not 1 <= limit <= 1000:
            raise HTTPException(400, '分页参数无效')
        with sessions() as db:
            card = db.get(Card, card_id)
            if not card:
                raise HTTPException(404, '卡片不存在')
            rows = db.scalars(select(Event).where(Event.leg_id.in_([l.id for l in card.legs])).order_by(Event.time.desc(), Event.id.desc()).offset(offset).limit(limit))
            return [dict(id=r.id, leg_id=r.leg_id, account=r.account, kind=r.kind, external_id=r.external_id, time=r.time, data=r.data) for r in rows]

    @app.get('/api/v1/cards/{card_id}/audit', dependencies=guard)
    def audit(card_id: str):
        with sessions() as db:
            return [dict(time=a.time, message=a.message) for a in db.scalars(select(Audit).where(Audit.card_id == card_id).order_by(Audit.time.desc()).limit(200))]

    @app.post('/api/v1/cards/{card_id}/cancel', dependencies=guard)
    async def cancel(card_id: str):
        async with service.lock:
            # Refresh first, so a not-yet-polled fill cannot be discarded.
            with sessions() as db:
                card = db.get(Card, card_id)
                if not card or card.status not in ('active', 'reconciling'):
                    raise HTTPException(409, '只能取消未成交的活跃卡片')
                leg_ids = [leg.id for leg in card.legs]
            from .models import now_ms
            try:
                for leg_id in leg_ids:
                    await service.sync_leg(leg_id, now_ms())
            except ExchangeError as exc:
                raise HTTPException(502, str(exc)) from None
            with sessions.begin() as db:
                card = db.get(Card, card_id)
                if any(leg.error for leg in card.legs) or db.scalar(select(Event.id).where(Event.leg_id.in_(leg_ids)).limit(1)):
                    raise HTTPException(409, '已有流水或核对异常，不能取消')
                card.status = 'cancelled'
                for leg in card.legs:
                    leg.reserved = False
                db.add(Audit(card_id=card.id, message='取消无成交卡片'))
            return {'status': 'cancelled'}

    return app


app = create_app()
