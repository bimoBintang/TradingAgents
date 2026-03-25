import urllib.request
import json
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
token = os.getenv("TURSO_AUTH_TOKEN")
host = "analysis-bimobintang.aws-us-east-1.turso.io"

# Test 1: sqlite+libsql://host/?authToken=token
url1 = f"sqlite+libsql://{host}/?authToken={token}"
try:
    e1 = create_engine(url1)
    with e1.connect() as c:
        print("Success URL 1")
except Exception as e:
    print("Failed URL 1:", e)

# Test 2: sqlite+libsql://host?authToken=token
url2 = f"sqlite+libsql://{host}?authToken={token}"
try:
    e2 = create_engine(url2)
    with e2.connect() as c:
        print("Success URL 2")
except Exception as e:
    print("Failed URL 2:", e)

# Test 3: wss://host/?authToken=token with sqlite+pysqlite? No, sqlite+libsql
url3 = f"sqlite+libsql://{host}"
try:
    e3 = create_engine(url3, connect_args={'auth_token': token})
    with e3.connect() as c:
        print("Success URL 3")
except Exception as e:
    print("Failed URL 3:", e)

