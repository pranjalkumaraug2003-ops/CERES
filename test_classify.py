import asyncio
from server.services.local_router_service import classify_intent

queries = [
    "hello",
    "what is the weather like in Delhi?",
    "play some music on my spotify playlist",
    "find directions to the nearest coffee shop",
    "check calendar events for today",
    "run a python script to test this",
    "send an email to boss saying I will be late",
    "how much is the gold rate today?",
    "what is the current CPU and RAM usage?",
    "what is your favorite movie?" # Should fall back to general
]

async def run():
    for q in queries:
        try:
            res = await classify_intent(q)
            print(f"Query: '{q}' -> Intent: {res['intent']} (confidence: {res['confidence']:.4f})")
        except Exception as e:
            print(f"Error on '{q}': {e}")

asyncio.run(run())
