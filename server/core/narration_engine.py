import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class NarrationUnsupported(Exception):
    """Raised when a tool result cannot be narrated by template and needs LLM fallback."""
    pass


# Tools whose own `summary` is already a well-formed spoken sentence, so an LLM
# call to rephrase it is pure waste — every one of these was previously costing a
# SECOND API request per query on top of the tool-decision call.
#
# e.g. get_unread_emails already returns:
#   "You have 3 unread emails. The latest is from Alice: 'Q3 numbers'."
#
# Deliberately NOT listed: search_web (a raw "Found 5 results" is a useless
# spoken answer — the snippets genuinely need synthesizing) and
# run_shell_command with real output (arbitrary stdout needs interpreting).
# Those two keep the LLM fallback, which is where it actually earns its cost.
SUMMARY_IS_SPEAKABLE = {
    "send_email",
    "get_unread_emails",
    "get_calendar_events",
    "delete_file",
}

def narrate(tool_name: str, result: Any) -> Optional[str]:
    """Generates a natural-sounding spoken response directly from a tool's result data.
    
    Returns a voice-ready string if supported, or None to fall back to Gemini narration.
    """
    logger.info(f"[NarrationEngine] Attempting template narration for tool '{tool_name}'...")
    if not result:
        logger.info(f"[NarrationEngine] Result is empty for tool '{tool_name}', falling back.")
        return None

    # Handle general error status by providing a quick verbal error report
    status = getattr(result, "status", "success")
    data = getattr(result, "data", {})
    summary = getattr(result, "summary", "")
    error_msg = getattr(result, "error", "")

    if status == "error":
        clean_err = str(error_msg or summary or "unspecified error")
        res_text = f"Sorry, I encountered an issue. {clean_err}."
        logger.info(f"[NarrationEngine] Tool '{tool_name}' failed with status error, returning voice error.")
        return res_text

    try:
        if tool_name == "get_weather":
            loc = data.get("location", "the requested location")
            forecast_days = data.get("forecast_days_requested", 1)
            daily = data.get("daily_forecast") or []

            # forecast_days >= 2 means a SPECIFIC future day was asked about
            # (weather_service treats forecast_days=2 as "today + tomorrow").
            # Previously this branch was unreachable: the "currently" fallback
            # below always fires because temp/humidity/feels_like are populated
            # from CURRENT conditions regardless of what day was requested — so
            # "what's tomorrow's weather" was silently answered with today's.
            if forecast_days == 2 and len(daily) >= 2:
                tomorrow = daily[-1]
                hi = tomorrow.get("high", "N/A").replace("°C", " degrees").replace("°F", " degrees")
                lo = tomorrow.get("low", "N/A").replace("°C", " degrees").replace("°F", " degrees")
                cond = tomorrow.get("condition", "unspecified conditions").lower()
                return f"Tomorrow in {loc}: expect {cond}, with a high of {hi} and a low of {lo}."

            if forecast_days >= 3 and daily:
                # A multi-day forecast was asked for — weather_service already
                # built a correct day-by-day summary; template narration adds
                # nothing here, so fall through to it via LLM/summary below.
                return summary or f"Here is the forecast for {loc}."

            # Data keys: location, temperature, feels_like, humidity, windspeed, condition
            temp = data.get("temperature", "").replace("°C", " degrees").replace("°F", " degrees")
            cond = data.get("condition", "unspecified conditions").lower()
            feels = data.get("feels_like", "").replace("°C", " degrees").replace("°F", " degrees")
            hum = data.get("humidity", "N/A")

            # Speak numbers nicely (e.g. 45% -> forty five percent)
            hum_spoken = hum.replace("%", " percent")

            if temp and hum != "N/A" and feels != "N/A":
                return f"Currently in {loc}: it is {cond}, {temp}, with a humidity of {hum_spoken}."
            return summary or f"The weather in {loc} is currently {cond} at {temp}."

        elif tool_name == "media_control":
            action = data.get("action", "")
            if action == "play_pause":
                return "Done. I've toggled playback."
            elif action == "next":
                return "Skipped to the next track."
            elif action == "prev":
                return "Returned to the previous track."
            elif action == "volume_up":
                return "Volume increased."
            elif action == "volume_down":
                return "Volume decreased."
            elif action == "mute":
                return "Muted system volume."
            return "Adjusted playback control."

        elif tool_name == "get_system_stats":
            # CPU, RAM, Disk, Battery
            cpu = data.get("cpu_percent")
            ram = data.get("ram_percent")
            bat = data.get("battery_percent")
            
            parts = []
            if cpu is not None:
                parts.append(f"CPU usage is at {int(cpu)} percent")
            if ram is not None:
                parts.append(f"RAM utilization is {int(ram)} percent")
            if bat is not None:
                parts.append(f"battery is at {int(bat)} percent")
                
            if parts:
                return "Current system stats: " + ", and ".join(parts) + "."
            return summary

        elif tool_name == "take_screenshot":
            return "Screenshot captured and saved to your desktop."

        elif tool_name == "lock_pc":
            return "PC locked."

        elif tool_name == "open_app":
            app = data.get("app_name", "the application")
            return f"Opening {app} now."

        elif tool_name == "close_application":
            app = data.get("app_name", "the application")
            return f"Closed {app}."

        elif tool_name == "create_reminder":
            title = data.get("title", "reminder")
            due = data.get("due_time", "scheduled time")
            return f"I've set a reminder to {title} for {due}."

        elif tool_name == "get_gold_price":
            # Data keys: gold_per_oz, gold_per_gram, currency
            g_oz = data.get("gold_per_oz")
            g_g = data.get("gold_per_gram")
            curr = data.get("currency", "U S dollars")
            if curr == "USD":
                curr = "dollars"
            elif curr == "INR":
                curr = "rupees"
            
            if g_oz and g_g:
                return f"Gold is trading at {g_oz} {curr} per ounce, which is about {g_g} {curr} per gram."
            return summary

        elif tool_name == "get_exchange_rate":
            # base, target, rate, amount, converted
            base = data.get("base", "")
            target = data.get("target", "")
            rate = data.get("rate")
            amount = data.get("amount", 1.0)
            converted = data.get("converted")
            
            if base and target and converted is not None:
                return f"{amount} {base} is equal to {converted} {target}, at an exchange rate of {rate}."
            return summary

        elif tool_name == "get_crypto_price":
            # symbol, price, currency, change_24h_percent
            sym = data.get("symbol", "").upper()
            price = data.get("price")
            curr = data.get("currency", "USD").upper()
            change = data.get("change_24h_percent")
            
            curr_str = "dollars" if curr == "USD" else curr.lower()
            
            if price is not None:
                msg = f"{sym} is currently trading at {price} {curr_str}."
                if change is not None:
                    dir_str = "up" if change >= 0 else "down"
                    msg += f" That is {dir_str} {abs(change)} percent over the last twenty four hours."
                return msg
            return summary

        elif tool_name == "open_url":
            url = data.get("url", "the webpage")
            return f"Opening link {url} in your browser."

        elif tool_name == "play_youtube":
            query = data.get("query", "your video")
            return f"Searching YouTube for {query}."

        elif tool_name == "open_maps":
            query = data.get("query", "your location")
            res_text = f"Opening Google Maps search for {query}."
            logger.info(f"[NarrationEngine] Template matched for '{tool_name}': '{res_text}'")
            return res_text

        elif tool_name == "run_shell_command":
            # Only narrate the trivial case. A command that produced real output
            # needs interpreting, which is a legitimate use of the LLM.
            stdout = str(data.get("stdout", "") or "").strip()
            if not stdout:
                return "Command completed with no output."
            logger.info(
                f"[NarrationEngine] '{tool_name}' produced output; using LLM to interpret it."
            )
            return None

        # Tools whose own summary is already voice-ready — no LLM needed.
        if tool_name in SUMMARY_IS_SPEAKABLE and summary:
            logger.info(f"[NarrationEngine] Using tool summary verbatim for '{tool_name}'.")
            return summary

        # Unsupported tools get routed to LLM narration
        logger.info(f"[NarrationEngine] Tool '{tool_name}' has no template; falling back to LLM.")
        return None

    except Exception as e:
        logger.error(f"[NarrationEngine] Error generating template narration for {tool_name}: {e}", exc_info=True)
        return None
