import asyncio
import httpx
import logging
import urllib.parse
import webbrowser
from typing import Optional, Dict, Any, List
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

logger = logging.getLogger(__name__)


async def search_web_tool(query: str) -> ToolResult:
    """Performs a web search using DuckDuckGo.
    Tries HTML scraping first; retries once on 202 (rate-limit); falls back to
    the DDG Instant Answer JSON API if scraping fails entirely.
    Results are UNTRUSTED context.
    """
    if not query:
        return ToolResult(status="error", data={}, summary="Query parameter is required.")

    query = query.strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # ── Attempt 1: DDG HTML scraping ──────────────────────────────────────────
    html_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    results: List[Dict[str, str]] = []

    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resp = await client.get(html_url, headers=headers)

            # 202 = DDG is rate-limiting / serving a JS challenge; wait briefly and retry once
            if resp.status_code == 202:
                logger.warning("[BrowserTools] DDG returned 202 (rate limit). Retrying after 1s...")
                await asyncio.sleep(1.0)
                resp = await client.get(html_url, headers=headers)

            if resp.status_code == 200:
                html = resp.text

                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "html.parser")
                    for r in soup.select(".result")[:5]:
                        title_elem = r.select_one(".result__a")
                        snippet_elem = r.select_one(".result__snippet")
                        if title_elem and snippet_elem:
                            results.append({
                                "title": title_elem.get_text().strip(),
                                "url": title_elem.get("href", "").strip(),
                                "snippet": snippet_elem.get_text().strip()
                            })
                except ImportError:
                    import re
                    links = re.findall(r'<a\s+class="result__a"\s+href="([^"]+)">([^<]+)</a>', html)
                    snippets = re.findall(r'<a\s+class="result__snippet"[^>]*>([^<]+)</a>', html)
                    for i in range(min(len(links), len(snippets), 5)):
                        results.append({
                            "title": links[i][1].strip(),
                            "url": links[i][0].strip(),
                            "snippet": snippets[i].strip()
                        })

                if results:
                    return ToolResult(
                        status="success",
                        data={"results": results, "query": query, "source": "ddg_html"},
                        summary=f"Found {len(results)} results for: '{query}'."
                    )
            else:
                logger.warning(f"[BrowserTools] DDG HTML scrape failed: HTTP {resp.status_code}")

    except Exception as e:
        logger.warning(f"[BrowserTools] DDG HTML scrape error: {e}", exc_info=True)

    # ── Attempt 2: DDG Instant Answer JSON API ────────────────────────────────
    # This endpoint is lighter, returns structured data, and is less rate-limited.
    try:
        ia_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            ia_resp = await client.get(ia_url, headers=headers)
            if ia_resp.status_code == 200:
                ia_data = ia_resp.json()
                abstract = ia_data.get("AbstractText", "").strip()
                abstract_url = ia_data.get("AbstractURL", "").strip()
                abstract_source = ia_data.get("AbstractSource", "").strip()
                related = ia_data.get("RelatedTopics", [])

                if abstract:
                    results.append({
                        "title": f"{abstract_source} — {query}" if abstract_source else query,
                        "url": abstract_url,
                        "snippet": abstract
                    })

                for topic in related[:4]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        results.append({
                            "title": topic.get("Text", "")[:80],
                            "url": topic.get("FirstURL", ""),
                            "snippet": topic.get("Text", "")
                        })

                if results:
                    return ToolResult(
                        status="success",
                        data={"results": results, "query": query, "source": "ddg_instant"},
                        summary=f"Found {len(results)} results for: '{query}'."
                    )
    except Exception as e:
        logger.warning(f"[BrowserTools] DDG Instant Answer API error: {e}", exc_info=True)

    # ── Fallback: direct search link ──────────────────────────────────────────
    fallback_url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}"
    return ToolResult(
        status="partial",
        data={
            "results": [{
                "title": f"Search results for '{query}'",
                "url": fallback_url,
                "snippet": f"Both scrapers failed. Click the link to view results for '{query}' on DuckDuckGo."
            }],
            "query": query,
            "source": "fallback_link"
        },
        summary=f"Web search degraded to direct link for: '{query}'."
    )


def open_url(url: str) -> ToolResult:
    """[DANGEROUS] Opens a specific URL in the default browser. Requires user confirmation.
    Use this when the user asks to navigate to a website, open a link, or visit a URL.
    """
    if not url or not url.strip():
        return ToolResult(status="error", data={}, summary="A URL is required.")

    target = url.strip()
    # Ensure proper scheme
    if not (target.startswith("http://") or target.startswith("https://")):
        target = "https://" + target

    try:
        opened = webbrowser.open(target)
        if opened:
            logger.info(f"[BrowserTools] Opened URL: {target}")
            return ToolResult(
                status="success",
                data={"url": target},
                summary=f"Opened {target} in the default browser."
            )
        else:
            err_msg = "webbrowser.open() returned False — no browser could be found."
            logger.error(f"[BrowserTools] {err_msg}")
            return ToolResult(
                status="error",
                data={"url": target},
                summary="Could not open URL. No default browser configured.",
                error=err_msg
            )
    except Exception as e:
        err_msg = f"Failed to open URL '{target}': {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"url": target},
            summary=f"Browser launch failed: {e}",
            error=err_msg
        )


def play_youtube(query: str) -> ToolResult:
    """[DANGEROUS] Searches YouTube for a video and opens the results page in the default browser.
    Use for requests like 'play Tanmay Bhat on YouTube' or 'open YouTube and search for X'.
    Requires user confirmation.
    """
    if not query or not query.strip():
        return ToolResult(status="error", data={}, summary="A search query is required.")

    search_query = query.strip()
    encoded = urllib.parse.quote(search_query)
    youtube_search_url = f"https://www.youtube.com/results?search_query={encoded}"

    try:
        opened = webbrowser.open(youtube_search_url)
        if opened:
            logger.info(f"[BrowserTools] YouTube search opened for: '{search_query}'")
            return ToolResult(
                status="success",
                data={"query": search_query, "url": youtube_search_url},
                summary=f"Opened YouTube search for '{search_query}' in your browser."
            )
        else:
            err_msg = "webbrowser.open() returned False — no browser could be launched."
            logger.error(f"[BrowserTools] {err_msg}")
            return ToolResult(
                status="error",
                data={"query": search_query},
                summary="Could not open YouTube. No default browser configured.",
                error=err_msg
            )
    except Exception as e:
        err_msg = f"Failed to open YouTube for '{search_query}': {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"query": search_query},
            summary=f"YouTube launch failed: {e}",
            error=err_msg
        )


def browser_automation(action: str, url: Optional[str] = None) -> ToolResult:
    """[DANGEROUS] Launches default web browser to navigate to a site. Requires user confirmation."""
    act = action.lower().strip()
    if not url:
        return ToolResult(status="error", data={}, summary="A URL parameter is required.")

    target_url = url.strip()
    if not (target_url.startswith("http://") or target_url.startswith("https://")):
        target_url = "https://" + target_url

    try:
        if act in ("open", "navigate", "go_to"):
            opened = webbrowser.open(target_url)
            if opened:
                return ToolResult(
                    status="success",
                    data={"action": act, "url": target_url},
                    summary=f"Opened browser and navigated to: {target_url}."
                )
            else:
                return ToolResult(
                    status="error",
                    data={"action": act, "url": target_url},
                    summary="No browser could be opened for navigation.",
                    error="webbrowser.open returned False"
                )
        else:
            return ToolResult(
                status="error",
                data={"action": act, "url": target_url},
                summary=f"Unsupported browser action: '{action}'."
            )
    except Exception as e:
        err_msg = f"Browser launch failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"action": act, "url": target_url},
            summary=f"Failed to open browser: {e}",
            error=err_msg
        )


def open_maps(query: str) -> ToolResult:
    """[DANGEROUS] Opens Google Maps in the default browser to search for a location or directions.
    Use when the user asks for directions, maps, location search, or navigation.
    Requires user confirmation.
    """
    if not query or not query.strip():
        return ToolResult(status="error", data={}, summary="A search query is required.")

    search_query = query.strip()
    encoded = urllib.parse.quote(search_query)
    maps_url = f"https://www.google.com/maps/search/?api=1&query={encoded}"

    try:
        opened = webbrowser.open(maps_url)
        if opened:
            logger.info(f"[BrowserTools] Google Maps opened for: '{search_query}'")
            return ToolResult(
                status="success",
                data={"query": search_query, "url": maps_url},
                summary=f"Opened Google Maps for '{search_query}' in your browser."
            )
        else:
            err_msg = "webbrowser.open() returned False — no browser could be launched."
            logger.error(f"[BrowserTools] {err_msg}")
            return ToolResult(
                status="error",
                data={"query": search_query},
                summary="Could not open Google Maps. No default browser configured.",
                error=err_msg
            )
    except Exception as e:
        err_msg = f"Failed to open Google Maps for '{search_query}': {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"query": search_query},
            summary=f"Google Maps launch failed: {e}",
            error=err_msg
        )


# Register with central executor
register_tool("search_web", search_web_tool)
register_tool("open_url", open_url)
register_tool("play_youtube", play_youtube)
register_tool("browser_automation", browser_automation)
register_tool("open_maps", open_maps)
