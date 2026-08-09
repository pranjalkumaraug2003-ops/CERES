import logging
import urllib.parse
import httpx
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Persistent global HTTP client for weather service to reuse TCP/SSL connection pools
_weather_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    follow_redirects=True
)

# Geocode cache: location_query -> (timestamp, lat, lon, resolved_name, country, timezone_str)
_geocode_cache: Dict[str, tuple] = {}

async def close_weather_client() -> None:
    """Closes the persistent weather HTTP client."""
    await _weather_http_client.aclose()

# WMO Weather Code -> human description
_WMO_CODES: Dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


async def get_weather(location: str, forecast_days: int = 1) -> Dict[str, Any]:
    """Retrieves weather for a given location using the Open-Meteo API.
    Supports current weather + daily forecasts up to 7 days.
    Two-step: geocoding -> forecast. Falls back to mock on any failure.
    
    Args:
        location: City name or location string.
        forecast_days: Number of days to forecast (1=today, 2=today+tomorrow, up to 7).
    """
    if not location:
        return {"error": "Location parameter is empty."}

    location = location.strip()
    forecast_days = max(1, min(forecast_days, 7))  # Clamp to [1, 7]

    try:
        # -- Step 1: Geocode (with 24h caching) --
        now_ts = time.time()
        cached = _geocode_cache.get(location)
        
        if cached and (now_ts - cached[0] < 86400.0):
            _, lat, lon, resolved_name, country, timezone_str = cached
            logger.info(f"[WeatherService] Geocode cache hit for '{location}': {resolved_name} ({lat}, {lon})")
        else:
            geocode_url = (
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote(location)}&count=1&language=en&format=json"
            )
            geo_resp = await _weather_http_client.get(geocode_url)

            if geo_resp.status_code != 200:
                logger.warning(
                    f"[WeatherService] Geocoding returned HTTP {geo_resp.status_code} "
                    f"for '{location}'. Body: {geo_resp.text[:200]}"
                )
                return _get_mock_weather(location)

            geo_data = geo_resp.json()
            results = geo_data.get("results")
            if not results:
                logger.warning(f"[WeatherService] No geocoding match for '{location}'.")
                return _get_mock_weather(location)

            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
            resolved_name = results[0].get("name", location)
            country = results[0].get("country", "")
            timezone_str = results[0].get("timezone", "auto")
            
            # Save to cache
            _geocode_cache[location] = (now_ts, lat, lon, resolved_name, country, timezone_str)

        # -- Step 2: Current weather + daily forecast --
        weather_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current_weather=true"
            "&hourly=relativehumidity_2m,apparent_temperature"
            "&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum"
            "&temperature_unit=celsius"
            "&windspeed_unit=kmh"
            f"&timezone={urllib.parse.quote(timezone_str)}"
            f"&forecast_days={forecast_days}"
        )
        wx_resp = await _weather_http_client.get(weather_url)

        if wx_resp.status_code != 200:
            logger.warning(
                f"[WeatherService] Forecast API returned HTTP {wx_resp.status_code}. "
                f"Body: {wx_resp.text[:200]}"
            )
            return _get_mock_weather(location)

        body = wx_resp.json()
        location_str = f"{resolved_name}, {country}".strip(", ")

        # -- Current weather --
        current = body.get("current_weather", {})
        temp = current.get("temperature")
        wind = current.get("windspeed")
        code = current.get("weathercode", 0)
        condition = _WMO_CODES.get(code, "Unspecified weather")

        # Pull first-hour humidity and apparent temp from hourly arrays
        hourly = body.get("hourly", {})
        humidity = None
        feels_like = None
        rh_list = hourly.get("relativehumidity_2m", [])
        at_list = hourly.get("apparent_temperature", [])
        if rh_list:
            humidity = rh_list[0]
        if at_list:
            feels_like = at_list[0]

        result: Dict[str, Any] = {
            "location": location_str,
            "temperature": f"{temp}\u00b0C",
            "feels_like": f"{feels_like}\u00b0C" if feels_like is not None else "N/A",
            "humidity": f"{humidity}%" if humidity is not None else "N/A",
            "windspeed": f"{wind} km/h",
            "condition": condition,
            "latitude": lat,
            "longitude": lon,
            "forecast_days_requested": forecast_days,
        }

        # -- Daily forecast data --
        daily = body.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        daily_codes = daily.get("weathercode", [])
        daily_precip = daily.get("precipitation_sum", [])

        forecast_list = []
        for i in range(min(len(dates), forecast_days)):
            day_data = {
                "date": dates[i],
                "high": f"{max_temps[i]}\u00b0C" if i < len(max_temps) else "N/A",
                "low": f"{min_temps[i]}\u00b0C" if i < len(min_temps) else "N/A",
                "condition": _WMO_CODES.get(daily_codes[i], "Unspecified") if i < len(daily_codes) else "N/A",
                "precipitation": f"{daily_precip[i]} mm" if i < len(daily_precip) else "N/A",
            }
            forecast_list.append(day_data)

        result["daily_forecast"] = forecast_list

        # -- Build human-readable summary --
        if forecast_days == 1:
            result["summary"] = (
                f"Currently in {location_str}: {condition.lower()}, {result['temperature']} "
                f"(feels like {result['feels_like']}), humidity {result['humidity']}, "
                f"wind at {result['windspeed']}."
            )
        else:
            day_summaries = []
            for d in forecast_list:
                day_summaries.append(
                    f"{d['date']}: {d['condition']}, high {d['high']}, low {d['low']}"
                )
            forecast_text = "; ".join(day_summaries)
            result["summary"] = (
                f"Weather in {location_str}: Currently {condition.lower()} at {result['temperature']}. "
                f"Forecast: {forecast_text}."
            )

        logger.info(f"[WeatherService] Fetched weather for '{location}' ({forecast_days} day(s)): {result['summary'][:100]}...")
        return result

    except httpx.TimeoutException:
        logger.warning(f"[WeatherService] Request timed out for '{location}'. Returning mock.")
    except Exception as e:
        logger.warning(f"[WeatherService] Unexpected error for '{location}': {e}. Returning mock.", exc_info=True)

    return _get_mock_weather(location)


def _get_mock_weather(location: str) -> Dict[str, Any]:
    """Fallback weather values when offline or facing network issues."""
    return {
        "location": f"{location} (offline fallback)",
        "temperature": "N/A",
        "feels_like": "N/A",
        "humidity": "N/A",
        "windspeed": "N/A",
        "condition": "Unavailable",
        "daily_forecast": [],
        "note": "Weather service unreachable. Check your network connection.",
        "summary": f"Sorry, I couldn't fetch live weather for {location} right now. Please check your internet connection.",
    }
