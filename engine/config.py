"""
Configuration loader and validator for the trading alert bot.
Loads config.yaml and .env into strongly-typed Pydantic models.
"""
from pathlib import Path
from typing import Any, Literal
import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SquareoffConfig(BaseModel):
    fno_stocks: str = "15:12"
    other_stocks: str = "15:25"


class BrokerConfig(BaseModel):
    name: str = "upstox"
    login_mode: Literal["manual", "auto_totp"] = "manual"
    callback_port: int = 8765
    squareoff: SquareoffConfig = Field(default_factory=SquareoffConfig)
    exit_buffer_min: int = 5
    entry_cutoff_min: int = 30


class RiskConfig(BaseModel):
    risk_per_trade_pct: float = 0.5
    max_notional_pct_mis: float = 200.0
    max_notional_pct_cnc: float = 50.0
    liquidity_cap_pct_adv: float = 0.5
    min_notional_inr: float = 5000.0
    max_open_trades: int = 4
    max_entries_per_day: int = 8
    daily_loss_stop_pct: float = 2.0
    max_consecutive_losses: int = 3
    pause_if_drawdown_x_backtest: float = 2.0


class WebPushConfig(BaseModel):
    enabled: bool = True
    ttl_entry_sec: int = 180
    ttl_exit_sec: int = 3600
    ttl_alert_sec: int = 3600


class TelegramConfig(BaseModel):
    enabled: bool = False


class NotifyConfig(BaseModel):
    min_strength: int = 6
    human_delay_sec: int = 45
    daily_summary: bool = False
    format: str = "standard"
    webpush: WebPushConfig = Field(default_factory=WebPushConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class PublishConfig(BaseModel):
    owner: str = ""
    repo: str = "intraday-alerts"
    data_branch: str = "data"
    path: str = "state.enc.json"
    min_interval_sec: int = 60
    heartbeat_sec: int = 300
    history_days: int = 30


class LlmConfig(BaseModel):
    model: str = "claude-opus-5-5"
    effort: str = "low"
    max_pages_text: int = 6
    max_pages_pdf: int = 8
    timeout_sec: int = 60
    max_retries: int = 2


class FilingsConfig(BaseModel):
    bse_poll_sec: int = 10
    nse_poll_sec: int = 30
    window_start: str = "09:15"
    dedupe_window_min: int = 60
    pdf_max_mb: int = 15


class UniverseConfig(BaseModel):
    min_price_inr: float = 50.0
    exclude_asm_stage_gte: int = 2
    exclude_gsm: bool = True


class S1ResultsConfig(BaseModel):
    enabled: bool = True
    mcap_cr: list[float] = Field(default_factory=lambda: [500.0, 15000.0])
    min_adv_cr: float = 3.0
    long_score_gte: int = 6
    short_score_lte: int = -6
    max_move_since_filing_pct: float = 2.0
    max_runup_30m_pct: float = 5.0
    min_band_room_pct: float = 3.0
    max_spread_pct: float = 0.5
    entry_slip_pct: float = 0.3
    entry_valid_min: int = 3
    exit: str = "news"


class S2OrbConfig(BaseModel):
    enabled: bool = True
    min_adv_cr: float = 10.0
    min_atr_pct: float = 1.0
    min_rvol: float = 1.0
    top_n: int = 20
    max_or_range_atr: float = 0.6
    trigger: Literal["close_1m", "first_touch"] = "close_1m"
    max_extension_pct: float = 0.4
    entry_slip_pct: float = 0.3
    entry_valid_min: int = 2
    entry_until: str = "11:00"
    max_trades_per_day: int = 3
    exit: str = "orb"


class SerialAnnouncerConfig(BaseModel):
    filings: int = 4
    days: int = 60
    strength_penalty: int = 2


class S3FilingFlashConfig(BaseModel):
    enabled: bool = True
    min_adv_cr: float = 2.0
    order_min_materiality_pct: float = 10.0
    order_min_mcap_pct_fallback: float = 5.0
    buyback_min_premium_pct: float = 15.0
    serial_announcer: SerialAnnouncerConfig = Field(default_factory=SerialAnnouncerConfig)
    blacklist: list[str] = Field(default_factory=list)
    max_move_since_filing_pct: float = 2.0
    max_runup_30m_pct: float = 5.0
    min_band_room_pct: float = 3.0
    entry_slip_pct: float = 0.3
    entry_valid_min: int = 3
    exit: str = "news"


class S4SquareoffConfig(BaseModel):
    collect: bool = True
    alerts_enabled: bool = False
    min_adv_cr: float = 5.0
    minutes_fno: list[str] = Field(default_factory=lambda: ["15:00", "15:05", "15:10", "15:12"])
    minutes_other: list[str] = Field(default_factory=lambda: ["15:15", "15:20", "15:25"])
    day_move_lte_pct: float = -3.0
    min_minute_drop_pct: float = 0.5
    hold_min: int = 5
    entry_slip_pct: float = 0.2
    safety_stop_pct: float = 1.0


class StrategiesConfig(BaseModel):
    s1_results: S1ResultsConfig = Field(default_factory=S1ResultsConfig)
    s2_orb: S2OrbConfig = Field(default_factory=S2OrbConfig)
    s3_filing_flash: S3FilingFlashConfig = Field(default_factory=S3FilingFlashConfig)
    s4_squareoff: S4SquareoffConfig = Field(default_factory=S4SquareoffConfig)


class NewsExitConfig(BaseModel):
    thesis: str = "ref_close"
    thesis_buffer_atr: float = 0.1
    safety_k_atr: float = 1.0
    safety_min_gap_atr: float = 0.25
    profit_lock: str = "avwap_after_2pct"
    max_hold_min: int | None = None
    target_atr: float | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_profit_lock(cls, data: Any) -> Any:
        if isinstance(data, dict) and "profit_lock" in data:
            if data["profit_lock"] is False:
                data["profit_lock"] = "off"
        return data


class OrbExitConfig(BaseModel):
    thesis: str = "or_far_close"
    safety_buffer_atr: float = 0.25
    profit_lock: str = "off"

    @model_validator(mode="before")
    @classmethod
    def normalize_profit_lock(cls, data: Any) -> Any:
        if isinstance(data, dict) and "profit_lock" in data:
            if data["profit_lock"] is False:
                data["profit_lock"] = "off"
        return data


class CommonExitConfig(BaseModel):
    candle_grace_sec: int = 2
    round_number_buffer_pct: float = 0.15


class ExitsConfig(BaseModel):
    news: NewsExitConfig = Field(default_factory=NewsExitConfig)
    orb: OrbExitConfig = Field(default_factory=OrbExitConfig)
    common: CommonExitConfig = Field(default_factory=CommonExitConfig)


class SlippageTier(BaseModel):
    adv_cr_gte: float
    pct: float


class CostsConfig(BaseModel):
    brokerage_pct: float = 0.03
    brokerage_cap_inr: float = 20.0
    stt_sell_pct: float = 0.025
    exchange_txn_pct: float = 0.00307
    sebi_per_crore_inr: float = 10.0
    stamp_buy_pct: float = 0.003
    gst_pct: float = 18.0
    slippage: list[SlippageTier] = Field(default_factory=list)
    news_extra_slippage_pct: float = 0.10


class CalendarConfig(BaseModel):
    extra_holidays: list[str] = Field(default_factory=list)


class YamlConfig(BaseModel):
    mode: Literal["paper", "live"] = "paper"
    timezone: str = "Asia/Kolkata"
    capital_inr: float = 500000.0
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    filings: FilingsConfig = Field(default_factory=FilingsConfig)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    exits: ExitsConfig = Field(default_factory=ExitsConfig)
    costs: CostsConfig = Field(default_factory=CostsConfig)
    fx: dict[str, float] = Field(default_factory=dict)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    ANTHROPIC_API_KEY: str = ""
    GITHUB_TOKEN: str = ""
    DATA_PASSPHRASE: str = ""
    VAPID_PRIVATE_KEY_PATH: str = "secrets/vapid_private.pem"
    VAPID_SUBJECT: str = "mailto:you@example.com"
    BROKER_API_KEY: str = ""
    BROKER_API_SECRET: str = ""
    BROKER_CLIENT_ID: str = ""
    BROKER_PASSWORD: str = ""
    BROKER_TOTP_SECRET: str = ""
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"


class Settings:
    """
    Combined settings exposing config.yaml sections directly and .env settings.
    """
    def __init__(self, yaml_cfg: YamlConfig, env_cfg: EnvSettings):
        self._yaml = yaml_cfg
        self._env = env_cfg

    @property
    def yaml(self) -> YamlConfig:
        return self._yaml

    @property
    def env(self) -> EnvSettings:
        return self._env

    # Direct access proxies to YAML config
    @property
    def mode(self) -> str:
        return self._yaml.mode

    @property
    def timezone(self) -> str:
        return self._yaml.timezone

    @property
    def capital_inr(self) -> float:
        return self._yaml.capital_inr

    @property
    def broker(self) -> BrokerConfig:
        return self._yaml.broker

    @property
    def risk(self) -> RiskConfig:
        return self._yaml.risk

    @property
    def notify(self) -> NotifyConfig:
        return self._yaml.notify

    @property
    def publish(self) -> PublishConfig:
        return self._yaml.publish

    @property
    def llm(self) -> LlmConfig:
        return self._yaml.llm

    @property
    def filings(self) -> FilingsConfig:
        return self._yaml.filings

    @property
    def universe(self) -> UniverseConfig:
        return self._yaml.universe

    @property
    def strategies(self) -> StrategiesConfig:
        return self._yaml.strategies

    @property
    def exits(self) -> ExitsConfig:
        return self._yaml.exits

    @property
    def costs(self) -> CostsConfig:
        return self._yaml.costs

    @property
    def fx(self) -> dict[str, float]:
        return self._yaml.fx

    @property
    def calendar(self) -> CalendarConfig:
        return self._yaml.calendar

    # Direct access proxies to env
    @property
    def ANTHROPIC_API_KEY(self) -> str:
        return self._env.ANTHROPIC_API_KEY

    @property
    def GITHUB_TOKEN(self) -> str:
        return self._env.GITHUB_TOKEN

    @property
    def DATA_PASSPHRASE(self) -> str:
        return self._env.DATA_PASSPHRASE

    @property
    def VAPID_PRIVATE_KEY_PATH(self) -> str:
        return self._env.VAPID_PRIVATE_KEY_PATH

    @property
    def VAPID_SUBJECT(self) -> str:
        return self._env.VAPID_SUBJECT

    @property
    def BROKER_API_KEY(self) -> str:
        return self._env.BROKER_API_KEY

    @property
    def BROKER_API_SECRET(self) -> str:
        return self._env.BROKER_API_SECRET

    @property
    def BROKER_CLIENT_ID(self) -> str:
        return self._env.BROKER_CLIENT_ID

    @property
    def BROKER_PASSWORD(self) -> str:
        return self._env.BROKER_PASSWORD

    @property
    def BROKER_TOTP_SECRET(self) -> str:
        return self._env.BROKER_TOTP_SECRET

    @property
    def TELEGRAM_BOT_TOKEN(self) -> str:
        return self._env.TELEGRAM_BOT_TOKEN

    @property
    def TELEGRAM_CHAT_ID(self) -> str:
        return self._env.TELEGRAM_CHAT_ID

    @property
    def NVIDIA_API_KEY(self) -> str:
        return self._env.NVIDIA_API_KEY

    @property
    def NVIDIA_BASE_URL(self) -> str:
        return self._env.NVIDIA_BASE_URL


_SETTINGS_INSTANCE: Settings | None = None


def load_config(config_path: str | Path = "config.yaml", env_file: str | Path = ".env") -> Settings:
    """
    Load and validate config.yaml and .env into typed Settings.
    Raises RuntimeError on missing or invalid configuration with clear messages.
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise RuntimeError(f"Configuration file not found: {config_file.resolve()}")

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}
    except Exception as e:
        raise RuntimeError(f"Failed to parse YAML file {config_file}: {e}") from e

    try:
        yaml_cfg = YamlConfig.model_validate(raw_data)
    except ValidationError as e:
        raise RuntimeError(f"Validation error in {config_file}:\n{e}") from e

    try:
        env_cfg = EnvSettings(_env_file=str(env_file) if Path(env_file).exists() else None)
    except Exception as e:
        raise RuntimeError(f"Failed to load environment variables from {env_file}: {e}") from e

    global _SETTINGS_INSTANCE
    _SETTINGS_INSTANCE = Settings(yaml_cfg, env_cfg)
    return _SETTINGS_INSTANCE


def get_settings() -> Settings:
    """
    Get or lazily load global settings singleton.
    """
    global _SETTINGS_INSTANCE
    if _SETTINGS_INSTANCE is None:
        _SETTINGS_INSTANCE = load_config()
    return _SETTINGS_INSTANCE
