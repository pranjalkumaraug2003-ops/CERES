import os
import json
import logging
import httpx
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent"


# Create once at module level for reusing connection pools (TCP/TLS keep-alive)
_http_client = httpx.AsyncClient(
    http2=True,
    timeout=httpx.Timeout(120.0, connect=10.0),
    limits=httpx.Limits(max_keepalive_connections=20, max_connections=50)
)

async def close_gemini_client() -> None:
    """Closes the global persistent HTTP client."""
    await _http_client.aclose()

class GeminiService:
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            logger.warning("[GeminiService] GOOGLE_API_KEY environment variable is not set.")

    async def generate_stream(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.4,
        max_output_tokens: Optional[int] = None
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """Queries Gemini 2.5 Flash using SSE streaming via httpx.AsyncClient.
        
        Uses `alt=sse` for Server-Sent Events — forces the HTTP layer to flush
        each token event immediately instead of buffering, giving true real-time
        token delivery.
        
        Yields events:
          - ("token", text_chunk)
          - ("function_call", (tool_name, args_dict))
          - ("error", error_message)
        """
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is missing from environment configuration.")

        # Build payload according to Google Generative Language REST API format
        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            "thinkingConfig": {
                "thinkingBudget": 0
            }
        }
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]

        # alt=sse forces Server-Sent Events format for true token-level streaming
        url = f"{GEMINI_API_URL}?key={self.api_key}&alt=sse"
        headers = {"Content-Type": "application/json"}
        
        # We pass timeout directly in the request stream context since _http_client is persistent
        timeout = httpx.Timeout(120.0, connect=10.0, read=120.0)

        try:
            async with _http_client.stream("POST", url, headers=headers, json=payload, timeout=timeout) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    err_msg = f"Gemini API error ({response.status_code}): {body.decode(errors='ignore')[:500]}"
                    logger.error(err_msg)
                    yield "error", err_msg
                    return

                # SSE format: each event is "data: {json}\n\n"
                # aiter_lines() gives us each line; SSE data lines start with "data: "
                async for line in response.aiter_lines():
                    line = line.strip()

                    # Skip empty lines and SSE event-type lines
                    if not line or line.startswith("event:"):
                        continue

                    # Strip the "data: " SSE prefix
                    if line.startswith("data: "):
                        json_str = line[6:]
                    elif line.startswith("data:"):
                        json_str = line[5:]
                    else:
                        # Not an SSE data line, skip
                        continue

                    # Handle SSE stream termination
                    if json_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(json_str)
                    except json.JSONDecodeError:
                        # Incomplete JSON fragment, skip
                        continue

                    # Extract candidates from the chunk
                    candidates = chunk.get("candidates", [])
                    if not candidates:
                        continue

                    candidate = candidates[0]
                    parts = candidate.get("content", {}).get("parts", [])

                    for part in parts:
                        if "text" in part:
                            yield "token", part["text"]
                        elif "functionCall" in part:
                            fc = part["functionCall"]
                            yield "function_call", (fc.get("name"), fc.get("args", {}))

        except httpx.HTTPError as e:
            err_msg = f"HTTP connection failure to Gemini: {e}"
            logger.error(err_msg, exc_info=True)
            yield "error", err_msg
