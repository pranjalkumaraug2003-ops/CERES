"""
profile_service.py — Singleton profile loader
Loads the user profile from Postgres once and caches it in memory.
Falls back to sensible defaults if not yet seeded.
"""
import json
from server.models.user_profile import UserProfile, Contact

_cached_profile: UserProfile | None = None

async def get_profile() -> UserProfile:
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile

    try:
        from server.services.postgres_service import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT data FROM user_profiles WHERE id = 'default' LIMIT 1")
            )
            row = result.fetchone()
            if row:
                data = row[0]
                if isinstance(data, str):
                    data = json.loads(data)
                contacts = [Contact(**c) for c in data.pop("contacts", [])]
                _cached_profile = UserProfile(**data, contacts=contacts)
                return _cached_profile
    except Exception as e:
        print(f"Profile load error: {e}")

    # Return default profile if nothing is seeded
    _cached_profile = UserProfile()
    return _cached_profile

async def save_profile(profile: UserProfile):
    global _cached_profile
    _cached_profile = profile
    try:
        from server.services.postgres_service import AsyncSessionLocal
        from sqlalchemy import text
        import json
        async with AsyncSessionLocal() as session:
            data = json.dumps(profile.to_dict())
            await session.execute(
                text("""
                    INSERT INTO user_profiles (id, data) VALUES ('default', :data)
                    ON CONFLICT (id) DO UPDATE SET data = :data
                """),
                {"data": data}
            )
            await session.commit()
    except Exception as e:
        print(f"Profile save error: {e}")

def invalidate_profile_cache():
    global _cached_profile
    _cached_profile = None
