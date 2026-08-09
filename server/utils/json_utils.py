import re

def clean_json_response(text: str) -> str:
    """Strip markdown fences Gemini sometimes wraps around JSON output."""
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()
