"""Local, read-only Grocious MCP server over stdio."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote, urlsplit
from urllib.request import Request, urlopen
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as error:  # pragma: no cover - exercised by the install command
    raise SystemExit("Install the optional MCP dependency with: uv pip install -r agent/requirements.txt") from error

mcp = FastMCP("Grocious")
API_BASE = os.environ.get("GROCIOUS_AGENT_API_URL", "http://127.0.0.1:3012/api/agent/v1").rstrip("/")
API_TOKEN = os.environ.get("GROCIOUS_AGENT_API_TOKEN", "")


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if not API_TOKEN:
        raise RuntimeError("Set GROCIOUS_AGENT_API_TOKEN in the MCP host configuration.")
    api_host = urlsplit(API_BASE)
    if api_host.scheme != "https" and api_host.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise RuntimeError("Use HTTPS for a non-local GROCIOUS_AGENT_API_URL.")
    url = f"{API_BASE}/{path}"
    if params:
        query = {key: value for key, value in params.items() if value is not None}
        url += "?" + urlencode(query)
    request = Request(url, headers={"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error", "request failed")
        except (ValueError, AttributeError):
            detail = "request failed"
        raise RuntimeError(f"Grocious API returned {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"Cannot reach Grocious at {API_BASE}: {error.reason}") from error


@mcp.tool()
def grocious_household_status() -> dict[str, Any]:
    """List household members, archive coverage, and per-account sync status."""
    return _get("household")


@mcp.tool()
def grocious_list_receipts(
    start_date: str,
    end_date: str,
    member_id: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    store: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_inbox: bool = False,
    include_lines: bool = False,
) -> dict[str, Any]:
    """List archived receipts; store filters retailer, provider filters connected account."""
    return _get(
        "receipts",
        {
            "start_date": start_date,
            "end_date": end_date,
            "member_id": member_id,
            "provider": provider,
            "source": source,
            "store": store,
            "limit": limit,
            "offset": offset,
            "include_inbox": str(include_inbox).lower(),
            "include_lines": str(include_lines).lower(),
        },
    )


@mcp.tool()
def grocious_get_receipt(source: str, archive_id: str) -> dict[str, Any]:
    """Get a normalized archived receipt, including line items and provenance."""
    return _get(f"receipts/{quote(source, safe='')}/{quote(archive_id, safe='')}")


@mcp.tool()
def grocious_spending_summary(
    start_date: str,
    end_date: str,
    member_id: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    group_by: str = "total",
    include_inbox: bool = False,
) -> dict[str, Any]:
    """Sum archived receipts; group by total, month, member, connected provider, or retailer (store)."""
    return _get(
        "spending",
        {
            "start_date": start_date,
            "end_date": end_date,
            "member_id": member_id,
            "provider": provider,
            "source": source,
            "group_by": group_by,
            "include_inbox": str(include_inbox).lower(),
        },
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
