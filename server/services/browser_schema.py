from typing import Literal, TypedDict, Optional

ActionType = Literal["navigate", "click", "type", "extract_text", "scroll"]

class BrowserAction(TypedDict):
    action: ActionType
    selector: Optional[str]
    value: Optional[str]
