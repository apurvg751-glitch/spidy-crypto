from typing import Union


# Precision specifications for Delta Exchange India perpetual contracts
SYMBOL_PRECISION_MAP: dict[str, int] = {
    "BTCUSD": 1,
    "ETHUSD": 2,
    "SOLUSD": 2,
    "BNBUSD": 2,
    "AVAXUSD": 3,
    "XRPUSD": 4,
}

SYMBOL_TICK_SIZE_MAP: dict[str, float] = {
    "BTCUSD": 0.1,
    "ETHUSD": 0.01,
    "SOLUSD": 0.01,
    "BNBUSD": 0.01,
    "AVAXUSD": 0.001,
    "XRPUSD": 0.0001,
}


def get_symbol_precision(symbol: str) -> int:
    """Returns the decimal precision for a given symbol."""
    return SYMBOL_PRECISION_MAP.get(symbol.upper(), 2)


def get_symbol_tick_size(symbol: str) -> float:
    """Returns the minimum price tick size for a given symbol."""
    return SYMBOL_TICK_SIZE_MAP.get(symbol.upper(), 0.01)


def round_price(symbol: str, price: Union[float, int]) -> float:
    """Rounds price to the correct decimal places according to exchange tick size."""
    if price is None:
        return 0.0
    dec = get_symbol_precision(symbol)
    return round(float(price), dec)


def format_price(symbol: str, price: Union[float, int]) -> str:
    """Formats price string with appropriate commas and decimal precision."""
    if price is None:
        return "--"
    p = float(price)
    dec = get_symbol_precision(symbol)
    return f"${p:,.{dec}f}"
