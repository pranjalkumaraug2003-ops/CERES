"""
user_profile.py — User identity model
Holds all personal data CERES needs to act as a personal assistant.
"""
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Contact:
    name: str
    relationship: str        # "friend", "family", "colleague", etc.
    email: Optional[str] = None
    phone: Optional[str] = None
    nickname: Optional[str] = None  # e.g. "Mom" → actual name "Sunita"

@dataclass
class UserProfile:
    # Identity
    name: str = "Pranjal"
    full_name: str = "Pranjal Sharma"
    dob: str = "2000-01-01"          # YYYY-MM-DD
    timezone: str = "Asia/Kolkata"
    location: str = "India"
    language: str = "en"

    # Preferences
    voice_name: str = "Charon"
    response_style: str = "concise"  # "concise" | "detailed"
    text_mode: bool = False           # True = show text, False = voice only

    # Contacts
    contacts: List[Contact] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Formats profile as a natural language context block for agent prompts."""
        from datetime import date
        today = date.today()
        try:
            birth = date.fromisoformat(self.dob)
            age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        except Exception:
            age = "unknown"

        contacts_str = ", ".join(
            f"{c.nickname or c.name} ({c.relationship})" for c in self.contacts[:10]
        ) or "No contacts saved yet."

        return f"""USER PROFILE:
Name: {self.name} ({self.full_name})
Age: {age} | DOB: {self.dob}
Location: {self.location} | Timezone: {self.timezone}
Key Contacts: {contacts_str}"""

    def find_contact(self, query: str) -> Optional[Contact]:
        """Fuzzy-resolve a name/nickname to a Contact."""
        query_lower = query.lower()
        for c in self.contacts:
            if query_lower in (c.name.lower(), (c.nickname or "").lower()):
                return c
        # partial match
        for c in self.contacts:
            if query_lower in c.name.lower():
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "dob": self.dob,
            "timezone": self.timezone,
            "location": self.location,
            "language": self.language,
            "voice_name": self.voice_name,
            "response_style": self.response_style,
            "text_mode": self.text_mode,
            "contacts": [
                {
                    "name": c.name,
                    "relationship": c.relationship,
                    "email": c.email,
                    "phone": c.phone,
                    "nickname": c.nickname,
                }
                for c in self.contacts
            ],
        }
