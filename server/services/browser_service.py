from playwright.async_api import async_playwright, Page, Browser
import json
from server.services.browser_schema import BrowserAction

class BrowserService:
    _instance = None

    def __init__(self):
        self.playwright = None
        self.browser: Browser = None
        self.page: Page = None

    @classmethod
    async def get_instance(cls):
        if cls._instance is None:
            cls._instance = BrowserService()
            await cls._instance.start()
        return cls._instance

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page()

    async def stop(self):
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
            
    async def execute_action(self, action: BrowserAction) -> str:
        act = action.get("action")
        selector = action.get("selector")
        value = action.get("value")

        try:
            if act == "navigate":
                await self.page.goto(value, wait_until="domcontentloaded")
                return f"Navigated to {value}"
            elif act == "click":
                await self.page.click(selector)
                return f"Clicked {selector}"
            elif act == "type":
                await self.page.fill(selector, value)
                return f"Typed '{value}' into {selector}"
            elif act == "extract_text":
                element = await self.page.query_selector(selector)
                text = await element.inner_text() if element else ""
                return f"Extracted text: {text}"
            elif act == "scroll":
                await self.page.evaluate(f"window.scrollBy(0, {value or 500})")
                return f"Scrolled down by {value or 500}px"
            else:
                return f"Unknown action: {act}"
        except Exception as e:
            return f"Error executing {act}: {str(e)}"
