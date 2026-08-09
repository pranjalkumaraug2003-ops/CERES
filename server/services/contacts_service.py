"""
contacts_service.py — Contacts resolution layer
Resolves natural language names ("Mom", "Rahul") to full contact records.
"""
from typing import Optional
from server.models.user_profile import Contact
from server.services.profile_service import get_profile


async def resolve_contact(name: str) -> Optional[Contact]:
    """Resolve a name or nickname to a Contact object."""
    profile = await get_profile()
    return profile.find_contact(name)


async def list_contacts() -> list[Contact]:
    profile = await get_profile()
    return profile.contacts


async def format_contacts_for_speech() -> str:
    contacts = await list_contacts()
    if not contacts:
        return "You have no contacts saved yet."
    parts = [f"{c.nickname or c.name}, your {c.relationship}" for c in contacts]
    return "Your contacts are: " + ", ".join(parts) + "."
