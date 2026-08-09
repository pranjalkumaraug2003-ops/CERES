import logging
import urllib.parse
import httpx
from typing import Dict, Any, Optional
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

logger = logging.getLogger(__name__)


async def get_exchange_rate(base: str, target: str, amount: float = 1.0) -> ToolResult:
    """Fetches live currency exchange rates from the open.er-api.com free API.
    Converts an amount from base currency to target currency.
    """
    base = base.upper().strip()
    target = target.upper().strip()

    if not base or not target:
        return ToolResult(status="error", data={}, summary="Both base and target currencies are required.")

    url = f"https://open.er-api.com/v6/latest/{base}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ToolResult(
                    status="error", data={"http_status": resp.status_code},
                    summary=f"Exchange rate API returned HTTP {resp.status_code}.",
                    error=f"HTTP {resp.status_code}"
                )

            data = resp.json()
            if data.get("result") != "success":
                return ToolResult(
                    status="error", data=data,
                    summary=f"Exchange rate API error: {data.get('error-type', 'unknown')}.",
                    error=data.get("error-type", "API error")
                )

            rates = data.get("rates", {})
            if target not in rates:
                available = ", ".join(sorted(rates.keys())[:20])
                return ToolResult(
                    status="error", data={"available_currencies": available},
                    summary=f"Currency '{target}' not found. Some available: {available}."
                )

            rate = rates[target]
            converted = round(amount * rate, 4)
            last_update = data.get("time_last_update_utc", "unknown")

            result = {
                "base": base,
                "target": target,
                "rate": rate,
                "amount": amount,
                "converted": converted,
                "last_updated": last_update,
            }
            result["summary"] = f"{amount} {base} = {converted} {target} (rate: {rate}, updated: {last_update})."
            logger.info(f"[FinanceTools] Exchange: {result['summary']}")
            return ToolResult(status="success", data=result, summary=result["summary"])

    except httpx.TimeoutException:
        return ToolResult(status="error", data={}, summary="Exchange rate request timed out.", error="Timeout")
    except Exception as e:
        logger.error(f"[FinanceTools] Exchange rate error: {e}", exc_info=True)
        return ToolResult(status="error", data={}, summary=f"Exchange rate lookup failed: {e}", error=str(e))


async def get_gold_price(currency: str = "USD") -> ToolResult:
    """Fetches current gold price using the XAU exchange rate API.
    Returns price per troy ounce and per gram.
    """
    currency = currency.upper().strip()

    # Direct query to XAU (gold ounce) from exchange rate API (bypassing broken metals.dev)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/XAU")
            if resp.status_code == 200:
                data = resp.json()
                rates = data.get("rates", {})
                if currency in rates:
                    price_per_oz = round(rates[currency], 2)
                    price_per_gram = round(price_per_oz / 31.1035, 2)
                    result = {
                        "gold_per_oz": price_per_oz,
                        "gold_per_gram": price_per_gram,
                        "currency": currency,
                        "source": "XAU exchange rate",
                    }
                    result["summary"] = f"Gold is currently at {price_per_oz} {currency} per ounce, or {price_per_gram} {currency} per gram."
                    logger.info(f"[FinanceTools] Gold: {result['summary']}")
                    return ToolResult(status="success", data=result, summary=result["summary"])
                else:
                    return ToolResult(status="error", data={}, summary=f"Currency '{currency}' not found in exchange rates.", error="Currency not found")
            else:
                return ToolResult(status="error", data={}, summary=f"Gold price API returned HTTP {resp.status_code}.", error=f"HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[FinanceTools] Gold price lookup failed: {e}", exc_info=True)
        return ToolResult(status="error", data={}, summary=f"Gold price lookup failed: {e}", error=str(e))


async def get_crypto_price(symbol: str, currency: str = "usd") -> ToolResult:
    """Fetches current cryptocurrency price from the CoinGecko free API.
    Supports BTC, ETH, SOL, DOGE, etc.
    """
    symbol = symbol.lower().strip()
    currency = currency.lower().strip()

    # Map common symbols to CoinGecko IDs
    symbol_map = {
        "btc": "bitcoin", "bitcoin": "bitcoin",
        "eth": "ethereum", "ethereum": "ethereum",
        "sol": "solana", "solana": "solana",
        "doge": "dogecoin", "dogecoin": "dogecoin",
        "ada": "cardano", "cardano": "cardano",
        "xrp": "ripple", "ripple": "ripple",
        "bnb": "binancecoin",
        "matic": "matic-network", "polygon": "matic-network",
        "dot": "polkadot", "polkadot": "polkadot",
        "avax": "avalanche-2", "avalanche": "avalanche-2",
        "link": "chainlink", "chainlink": "chainlink",
    }
    coin_id = symbol_map.get(symbol, symbol)

    url = (
        f"https://api.coingecko.com/api/v3/simple/price"
        f"?ids={urllib.parse.quote(coin_id)}"
        f"&vs_currencies={urllib.parse.quote(currency)}"
        f"&include_24hr_change=true"
        f"&include_market_cap=true"
    )

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ToolResult(
                    status="error", data={"http_status": resp.status_code},
                    summary=f"CoinGecko API returned HTTP {resp.status_code}.",
                    error=f"HTTP {resp.status_code}"
                )

            data = resp.json()
            coin_data = data.get(coin_id)
            if not coin_data:
                return ToolResult(
                    status="error", data={"queried_id": coin_id},
                    summary=f"Cryptocurrency '{symbol}' not found on CoinGecko."
                )

            price = coin_data.get(currency)
            change_24h = coin_data.get(f"{currency}_24h_change")
            market_cap = coin_data.get(f"{currency}_market_cap")

            result = {
                "symbol": symbol.upper(),
                "coin_id": coin_id,
                "price": price,
                "currency": currency.upper(),
                "change_24h_percent": round(change_24h, 2) if change_24h else None,
                "market_cap": market_cap,
            }

            change_str = ""
            if change_24h is not None:
                direction = "up" if change_24h >= 0 else "down"
                change_str = f", {direction} {abs(round(change_24h, 2))}% in 24h"

            result["summary"] = f"{symbol.upper()} is at {price} {currency.upper()}{change_str}."
            logger.info(f"[FinanceTools] Crypto: {result['summary']}")
            return ToolResult(status="success", data=result, summary=result["summary"])

    except httpx.TimeoutException:
        return ToolResult(status="error", data={}, summary="Crypto price request timed out.", error="Timeout")
    except Exception as e:
        logger.error(f"[FinanceTools] Crypto price error: {e}", exc_info=True)
        return ToolResult(status="error", data={}, summary=f"Crypto price lookup failed: {e}", error=str(e))


# Register with central executor
register_tool("get_exchange_rate", get_exchange_rate)
register_tool("get_gold_price", get_gold_price)
register_tool("get_crypto_price", get_crypto_price)
