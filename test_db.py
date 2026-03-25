import os
import asyncio
import libsql_client
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if url.startswith("sqlite+libsql://"):
    url = url.replace("sqlite+libsql://", "libsql://")

async def main():
    print(f"Connecting to {url}")
    try:
        async with libsql_client.create_client(url) as client:
            res = await client.execute("SELECT 1")
            print("Connected!", res)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
