"""Caller identity for user-scoped MCP tools.

Every agent connects to the MCP server with an `X-User-Id` header that binds the
connection to exactly one user. Tools read the caller's id from that header rather
than accepting it as an LLM-supplied argument. This enforces the spec's guarantee
that an agent can only act for its own user, and removes the entire class of bugs
where the model passes the wrong id.
"""
from fastmcp.server.dependencies import get_http_headers


class IdentityError(Exception):
    pass


def caller_id() -> str:
    """Return the user id bound to this MCP connection, or raise IdentityError."""
    headers = get_http_headers(include_all=True)
    # header keys are normalized to lowercase by FastMCP
    uid = headers.get("x-user-id")
    if not uid:
        raise IdentityError(
            "No X-User-Id header on the request — agent identity is not established."
        )
    return uid
