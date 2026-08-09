from typing import Any, Dict, Optional

class ToolResult:
    """Normalizes all tool execution outputs.
    Ensures analytics, logging, and future agent chaining systems
    interact with a standard, predictable data format.
    """
    def __init__(
        self,
        status: str,  # "success" | "error" | "partial" | "requires_confirmation"
        data: Dict[str, Any],
        summary: str,
        error: Optional[str] = None
    ):
        self.status = status
        self.data = data
        self.summary = summary
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "summary": self.summary,
            "error": self.error
        }
