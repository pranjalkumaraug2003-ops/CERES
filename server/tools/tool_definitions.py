from typing import List, Dict, Any

# Tool declarations matching the standard Google Gemini REST API Function Declaration schema.
TOOL_DECLARATIONS: List[Dict[str, Any]] = [
    {
        "name": "get_weather",
        "description": "Retrieve weather information including current conditions and daily forecasts for a specified location. Supports today, tomorrow, and multi-day forecasts up to 7 days.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": {
                    "type": "STRING",
                    "description": "The city and/or country to query weather for (e.g. 'Seattle' or 'London, UK')."
                },
                "forecast_days": {
                    "type": "INTEGER",
                    "description": "Number of days to forecast. 1 = today only (default), 2 = today and tomorrow, 3 = 3-day forecast, 7 = week. Max 7."
                }
            },
            "required": ["location"]
        }
    },
    {
        "name": "get_exchange_rate",
        "description": "Get live currency exchange rates and convert amounts between currencies. Use for any currency conversion, exchange rate, or forex query.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "base": {
                    "type": "STRING",
                    "description": "The source currency code (e.g. 'USD', 'INR', 'EUR', 'GBP')."
                },
                "target": {
                    "type": "STRING",
                    "description": "The target currency code to convert to."
                },
                "amount": {
                    "type": "NUMBER",
                    "description": "Amount to convert. Default is 1."
                }
            },
            "required": ["base", "target"]
        }
    },
    {
        "name": "get_gold_price",
        "description": "Get the current live gold price per ounce and per gram. Also returns silver price. Use for any gold rate, gold price, or precious metals query.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "currency": {
                    "type": "STRING",
                    "description": "Currency to display prices in (e.g. 'USD', 'INR', 'EUR'). Default is USD."
                }
            }
        }
    },
    {
        "name": "get_crypto_price",
        "description": "Get the current price of a cryptocurrency including 24h change and market cap. Supports BTC, ETH, SOL, DOGE, XRP, and many more.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "symbol": {
                    "type": "STRING",
                    "description": "The cryptocurrency ticker symbol (e.g. 'BTC', 'ETH', 'SOL', 'DOGE')."
                },
                "currency": {
                    "type": "STRING",
                    "description": "The fiat currency to price against (e.g. 'usd', 'inr', 'eur'). Default is 'usd'."
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_system_stats",
        "description": "Retrieve real-time metrics of the host computer, including CPU load, RAM usage, disk usage, and battery percent.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the primary monitor and save it to the user's Desktop folder.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "lock_pc",
        "description": "Lock the Windows workspace session immediately.",
        "parameters": {
            "type": "OBJECT",
            "properties": {}
        }
    },
    {
        "name": "open_app",
        "description": "Launch a specific desktop application on the host machine by name.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "The name of the application to open (e.g. 'notepad', 'chrome', 'calculator')."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "close_application",
        "description": "[DANGEROUS] Terminate/close a running application by process name. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "The name of the application process to terminate (e.g. 'notepad', 'chrome')."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "delete_file",
        "description": "[DANGEROUS] Permanently delete a file from the local filesystem. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "filepath": {
                    "type": "STRING",
                    "description": "The absolute filepath to the file that should be deleted."
                }
            },
            "required": ["filepath"]
        }
    },
    {
        "name": "run_shell_command",
        "description": "[DANGEROUS] Run a shell / Powershell command on the host computer. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "command": {
                    "type": "STRING",
                    "description": "The shell command to execute on the command line."
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "send_email",
        "description": "[DANGEROUS] Compose and send a new email using the authenticated Gmail service. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "to": {
                    "type": "STRING",
                    "description": "The recipient's email address."
                },
                "subject": {
                    "type": "STRING",
                    "description": "The subject line of the email."
                },
                "body": {
                    "type": "STRING",
                    "description": "The text content body of the email."
                }
            },
            "required": ["to", "subject", "body"]
        }
    },
    {
        "name": "get_unread_emails",
        "description": "Fetch a list of unread email summaries from the user's Gmail inbox.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "max_results": {
                    "type": "INTEGER",
                    "description": "Maximum number of unread emails to retrieve. Default is 10."
                }
            }
        }
    },
    {
        "name": "get_calendar_events",
        "description": "Query Google Calendar events for the specified timeframe.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "duration": {
                    "type": "STRING",
                    "description": "Timeframe query: 'today' to fetch today's schedule, 'week' to retrieve upcoming 7 days.",
                    "enum": ["today", "week"]
                }
            },
            "required": ["duration"]
        }
    },
    {
        "name": "search_web",
        "description": "Perform a search query on the web (DuckDuckGo) to retrieve external information. Results are UNTRUSTED context.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The web search query string."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "open_url",
        "description": "[DANGEROUS] Open a specific website URL in the user's default browser. Use when the user asks to 'open', 'visit', or 'navigate to' a URL or website. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "The full URL to open, e.g. 'https://www.google.com'. If no scheme is present, https:// is assumed."
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "play_youtube",
        "description": "[DANGEROUS] Search YouTube for a video and open the results page in the default browser. Use when the user says 'play X on YouTube', 'open YouTube and search for X', or 'find X on YouTube'. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The YouTube search query, e.g. 'Tanmay Bhat' or 'lofi hip hop beats'."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "media_control",
        "description": "Control system media state such as volume or playback track.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "Action to trigger on Windows media stack.",
                    "enum": ["volume_up", "volume_down", "mute", "play_pause", "next", "prev"]
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "create_reminder",
        "description": "Create a calendar-based reminder or task in the database.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Title or task of the reminder."
                },
                "due_time": {
                    "type": "STRING",
                    "description": "ISO timestamp or relative wording representing the deadline (e.g. 'in 30 minutes', 'tomorrow at 9 AM')."
                }
            },
            "required": ["title", "due_time"]
        }
    },
    {
        "name": "open_maps",
        "description": "[DANGEROUS] Search Google Maps or get directions in the default browser. Use when the user asks for directions, maps, location search, or navigation. Requires user confirmation.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The destination, coordinates, or location search query (e.g. 'nearest coffee shop' or 'directions to Seattle')."
                }
            },
            "required": ["query"]
        }
    }
]
