from typing import Optional, Literal
from pydantic import BaseModel, Field


class Candle(BaseModel):
    time: int = Field(..., description="Unix timestamp in seconds")
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True

    @property
    def hl2(self) -> float:
        return (self.high + self.low) / 2.0

    @property
    def hlc3(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def ohlc4(self) -> float:
        return (self.open + self.high + self.low + self.close) / 4.0

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        return max(self.high - self.low, 1e-6)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


class Ticker(BaseModel):
    symbol: str
    mark_price: float
    last_price: float
    volume_24h: Optional[float] = 0.0
    change_24h: Optional[float] = 0.0
    timestamp: int


class OrderBlock(BaseModel):
    id: str
    symbol: str
    direction: Literal["BULLISH", "BEARISH"]
    top: float
    bottom: float
    candle_index: int
    creation_time: int
    is_mitigated: bool = False
    is_invalidated: bool = False
    structure_break_ref: Optional[str] = None

    @property
    def is_fresh(self) -> bool:
        return not self.is_mitigated and not self.is_invalidated


class FairValueGap(BaseModel):
    id: str
    symbol: str
    direction: Literal["BULLISH", "BEARISH"]
    top: float
    bottom: float
    candle_index: int
    creation_time: int
    fill_pct: float = 0.0
    is_mitigated: bool = False
    is_invalidated: bool = False


class MultiTimeframeContext(BaseModel):
    symbol: str
    macro_bias_4h: str = "Neutral"       # Bullish / Bearish / Neutral
    trend_1h: str = "Neutral"            # Bullish / Bearish / Neutral
    exec_context_15m: str = "Neutral"    # Bullish / Bearish / Neutral
    struct_5m: str = "Neutral"           # Bullish / Bearish / Neutral
    ema200_bias: str = "Neutral"         # Price above / below 200 EMA
    alignment_score: int = 0             # 0 - 100 alignment score


class ConfirmationsResult(BaseModel):
    trend_ok: bool = False
    ob_ok: bool = False
    fvg_ok: bool = False
    volume_ok: bool = False
    momentum_ok: bool = False
    ema_ok: bool = False
    candle_ok: bool = False
    passed_count: int = 0
    is_qualified: bool = False           # >= 4/7
    rating: str = "UNQUALIFIED"          # QUALIFIED (4), STRONG (5), VERY STRONG (6), EXCEPTIONAL (7)
    details: dict[str, str] = Field(default_factory=dict)


class MarketState(BaseModel):
    symbol: str
    current_price: float = 0.0
    last_update_ts: int = 0
    is_stale: bool = False
    candles_5m: list[Candle] = Field(default_factory=list)
    candles_15m: list[Candle] = Field(default_factory=list)
    candles_1h: list[Candle] = Field(default_factory=list)
    candles_4h: list[Candle] = Field(default_factory=list)
    connection_status: str = "DISCONNECTED"
    mtf_context: Optional[MultiTimeframeContext] = None
