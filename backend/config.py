from decimal import Decimal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_user: str = 'admin'
    app_password: SecretStr = SecretStr('')
    database_url: str = 'sqlite:///data/arbi.db'
    poll_seconds: int = Field(default=60, ge=10)
    stale_seconds: int = Field(default=180, ge=30)
    snapshot_retention_days: int = Field(default=30, ge=1)
    omni_enabled: bool = True
    imbalance_ratio: Decimal = Field(default=Decimal('.01'), ge=0)
    max_leverage: Decimal = Field(default=Decimal('5'), gt=0)
    max_margin_usage: Decimal = Field(default=Decimal('.7'), gt=0)
    min_liquidation_distance: Decimal = Field(default=Decimal('.1'), ge=0)
    binance_api_key: SecretStr = SecretStr('')
    binance_api_secret: SecretStr = SecretStr('')
    aster_user: str = ''
    aster_signer: str = ''
    aster_private_key: SecretStr = SecretStr('')
