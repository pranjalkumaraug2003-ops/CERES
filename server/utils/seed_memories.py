import asyncio
import os
import sys

# Add parent dir to path so we can import server.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from server.services.qdrant_service import init_qdrant, store_memory
from server.services.postgres_service import init_postgres, log_episodic_memory

async def main():
    print("Initializing databases...")
    await init_qdrant()
    await init_postgres()

    seed_facts = [
        "User prefers React, TypeScript, and TailwindCSS.",
        "User is actively seeking a frontend software engineering internship.",
        "User is based in Bangalore, India.",
        "User dislikes boilerplate code and prefers concise architectures."
    ]

    print("Seeding memories...")
    for fact in seed_facts:
        await store_memory(fact, importance=1.0)
        await log_episodic_memory(fact, "seed_script", importance=1.0)
        print(f"Seeded: {fact}")
        
    print("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(main())
