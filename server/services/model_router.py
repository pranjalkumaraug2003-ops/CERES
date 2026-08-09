from langchain_google_genai import ChatGoogleGenerativeAI

FLASH = "gemini-2.5-flash"
PRO   = "gemini-2.5-pro"

def get_flash(temperature: float = 0) -> ChatGoogleGenerativeAI:
    """For Memory Agent, Memory Writer, Automation Agent, Reflection Agent."""
    return ChatGoogleGenerativeAI(model=FLASH, temperature=temperature)

def get_pro(temperature: float = 0) -> ChatGoogleGenerativeAI:
    """For Orchestrator and Communication Agent only."""
    return ChatGoogleGenerativeAI(model=PRO, temperature=temperature)
