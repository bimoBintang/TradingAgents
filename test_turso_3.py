import os
from sqlalchemy.dialects import registry
from sqlalchemy import create_engine

token = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NzQwNjE1MDksImlkIjoiMDE5ZDBlM2MtOWMwMS03OWE0LTlmYWUtMzE5MDNlYjczOWY1IiwicmlkIjoiZDBhZGViODEtN2UxNy00NmRiLWIyYWMtNmU5NGMzN2MxNGQ2In0.WBGrzWfQoBzOSTCDBfp17fSBQVivlM6sPF4LBDR5sJyrpWEJuzD8RCADbqQJKX5Lgkj2fnzrRvwADN8KJ3emAg"
host = "analysis-bimobintang.aws-us-east-1.turso.io"

registry.register("sqlite.wss", "sqlalchemy_libsql.dialect", "dialect")

try:
    e = create_engine(f"sqlite+wss://{host}/?authToken={token}")
    with e.connect() as c:
        print("Success with sqlite+wss")
except Exception as err:
    print("Failed sqlite+wss:", err)

