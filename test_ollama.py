import httpx
import asyncio
import json

async def run():
    try:
        async with httpx.AsyncClient() as c:
            r = await c.post('http://localhost:11434/api/generate', json={'model':'phi3:mini', 'prompt':'Classify: hello', 'stream':False, 'format':'json'})
            print(r.json())
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(run())
