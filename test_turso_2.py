import urllib.request
import os
import asyncio
import libsql_client

token = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NzQwNjE1MDksImlkIjoiMDE5ZDBlM2MtOWMwMS03OWE0LTlmYWUtMzE5MDNlYjczOWY1IiwicmlkIjoiZDBhZGViODEtN2UxNy00NmRiLWIyYWMtNmU5NGMzN2MxNGQ2In0.WBGrzWfQoBzOSTCDBfp17fSBQVivlM6sPF4LBDR5sJyrpWEJuzD8RCADbqQJKX5Lgkj2fnzrRvwADN8KJ3emAg"
host = "analysis-bimobintang.aws-us-east-1.turso.io"

async def test_conn(url):
    try:
        async with libsql_client.create_client(url) as client:
            res = await client.execute("SELECT 1")
            print(f"Success with {url}")
    except Exception as e:
        print(f"Failed with {url}: {e}")

async def main():
    await test_conn(f"libsql://{host}/?authToken={token}")
    await test_conn(f"https://{host}/?authToken={token}")
    await test_conn(f"wss://{host}/?authToken={token}")

asyncio.run(main())
