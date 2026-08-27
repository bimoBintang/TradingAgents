"""Clerk bearer-token verification for the MCP server's HTTP transport.

Only used when MCP_TRANSPORT=streamable-http (see server.py). The
stdio transport (the default, for a single local user running Claude
Desktop/Code on their own machine) has no HTTP request to carry a
token, so it doesn't go through this at all — see context.py's
resolve_mcp_user() for how identity is fixed there instead.

This reuses the exact same JWT verification and user-upsert logic as
the REST API (api/auth.py) — not a second, divergent implementation —
so a Clerk session is valid against both surfaces identically.
"""

from __future__ import annotations

import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from api.auth import ClerkTokenInvalid, verify_clerk_jwt

logger = logging.getLogger("mcp_server.auth")


class ClerkTokenVerifier(TokenVerifier):
    """Verifies a Clerk-issued JWT passed as the MCP request's Bearer token."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            clerk_id = verify_clerk_jwt(token)
        except ClerkTokenInvalid as e:
            logger.warning("Rejected MCP bearer token: %s", e)
            return None

        # `subject` is what resolve_mcp_user() (context.py) reads back out
        # via get_access_token() to look up/create the acting User — see
        # get_or_create_user_by_clerk_id in api/auth.py.
        return AccessToken(token=token, client_id="clerk", scopes=[], subject=clerk_id)
