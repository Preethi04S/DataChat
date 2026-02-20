"""
Currency engine – fetches live exchange rates and converts USD prices.
Falls back to hardcoded approximate rates if the API is unavailable.
"""
import os
import time
import requests

# Fallback rates (USD base, approximate)
FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0,
    "INR": 83.5,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.5,
    "BRL": 4.97,
    "AUD": 1.53,
    "CAD": 1.36,
    "SGD": 1.34,
    "MXN": 17.1,
}

_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 3600  # 1 hour


def get_rates() -> dict[str, float]:
    """Return exchange rates (USD base). Uses cache or free API."""
    global _cache, _cache_ts
    if _cache and (time.time() - _cache_ts) < CACHE_TTL:
        return _cache

    api_key = os.getenv("EXCHANGE_RATE_API_KEY", "")
    if api_key:
        try:
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/USD"
            resp = requests.get(url, timeout=5)
            data = resp.json()
            if data.get("result") == "success":
                _cache = data["conversion_rates"]
                _cache_ts = time.time()
                return _cache
        except Exception:
            pass

    # Secondary free API (no key needed)
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
        data = resp.json()
        _cache = data.get("rates", FALLBACK_RATES)
        _cache_ts = time.time()
        return _cache
    except Exception:
        return FALLBACK_RATES


def convert_price(usd_price: float, target_currency: str) -> dict:
    """Convert USD price to target currency."""
    rates = get_rates()
    target = target_currency.upper()
    if target not in rates:
        return {"error": f"Unknown currency: {target_currency}"}
    converted = round(usd_price * rates[target], 2)
    symbol = _symbols().get(target, target)
    return {
        "usd": usd_price,
        "currency": target,
        "amount": converted,
        "display": f"{symbol}{converted:,.2f} {target}",
        "rate": rates[target],
    }


def convert_multiple(usd_price: float, currencies: list[str]) -> dict:
    """Convert to multiple currencies at once."""
    return {c: convert_price(usd_price, c) for c in currencies}


def _symbols() -> dict[str, str]:
    return {
        "USD": "$", "INR": "₹", "EUR": "€", "GBP": "£",
        "JPY": "¥", "BRL": "R$", "AUD": "A$", "CAD": "C$",
        "SGD": "S$", "MXN": "MX$",
    }
