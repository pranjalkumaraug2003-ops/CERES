"""
seed_profile.py — CLI to seed your personal profile into CERES.
Run once from the project root:
    python -m server.utils.seed_profile
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from server.models.user_profile import UserProfile, Contact
from server.services.postgres_service import init_postgres

DEFAULT_PROFILE = UserProfile(
    name="Pranjal",
    full_name="Pranjal Sharma",
    dob="2005-01-01",          # ← Update your real DOB
    timezone="Asia/Kolkata",
    location="India",
    voice_name="Charon",
    response_style="concise",
    contacts=[
        # ← Add your real contacts here
        Contact(name="Mom", relationship="family", email="mom@example.com", nickname="Mom"),
        Contact(name="Rahul", relationship="friend", email="rahul@example.com"),
    ]
)

async def seed():
    print("Initializing database...")
    await init_postgres()

    from server.services.profile_service import save_profile
    print(f"Seeding profile for: {DEFAULT_PROFILE.full_name}")
    await save_profile(DEFAULT_PROFILE)
    print("✅ Profile seeded successfully!")
    print(f"   Name: {DEFAULT_PROFILE.name}")
    print(f"   DOB:  {DEFAULT_PROFILE.dob}")
    print(f"   Contacts: {len(DEFAULT_PROFILE.contacts)}")

if __name__ == "__main__":
    asyncio.run(seed())
