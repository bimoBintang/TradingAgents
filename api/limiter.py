"""Rate Limiter for the FastAPI application."""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

# Identify users by their IP address
limiter = Limiter(key_func=get_remote_address)
