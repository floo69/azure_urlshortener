"""Azure Functions HTTP layer: request in, JSON/redirect out. Business rules live in shortener.py."""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import azure.functions as func

from shortener import (
    AzureTableStore,
    CollisionError,
    InMemoryStore,
    InvalidURLError,
    StorageError,
    create_short_link,
    lookup_link,
)

# Anonymous: visitors must open short links without a function key in the URL.
# host.json sets routePrefix to "" so routes are /links and /{code}, not /api/....
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# Reused across requests in the same worker. Memory backend must be a singleton
# or every request would start with an empty dict.
_store = None


def get_store():
    global _store
    if _store is not None:
        return _store

    backend = os.environ.get("STORAGE_BACKEND", "azure").strip().lower()
    if backend == "memory":
        _store = InMemoryStore()
        return _store

    connection = os.environ.get("STORAGE_CONNECTION_STRING") or os.environ.get(
        "AzureWebJobsStorage", ""
    )
    table_name = os.environ.get("TABLE_NAME", "links")
    _store = AzureTableStore(connection, table_name)
    return _store


def cors_headers() -> dict[str, str]:
    """Browser calls from the static frontend. Origin comes from env, never hardcoded *."""
    origin = os.environ.get("CORS_ALLOWED_ORIGIN", "").strip()
    headers = {
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def json_response(payload: dict, status: int) -> func.HttpResponse:
    headers = {"Content-Type": "application/json"}
    headers.update(cors_headers())
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status,
        headers=headers,
        mimetype="application/json",
    )


def public_base_url(req: func.HttpRequest) -> str:
    """Build https://host for short_url. Prefer proxy headers Azure sets in front of the app."""
    proto = req.headers.get("X-Forwarded-Proto") or urlparse(req.url).scheme or "https"
    host = (
        req.headers.get("X-Forwarded-Host")
        or req.headers.get("Host")
        or urlparse(req.url).netloc
    )
    return f"{proto}://{host}".rstrip("/")


@app.route(route="links", methods=["POST", "OPTIONS"])
def create_link(req: func.HttpRequest) -> func.HttpResponse:
    # Preflight: the browser sends OPTIONS before POST when the page is on another origin.
    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers())

    try:
        body = req.get_json()
    except ValueError:
        return json_response({"error": "Body must be JSON with a 'url' field"}, 400)

    if not isinstance(body, dict) or "url" not in body:
        return json_response({"error": "Body must be JSON with a 'url' field"}, 400)

    try:
        link = create_short_link(get_store(), body["url"])
    except InvalidURLError as exc:
        return json_response({"error": str(exc)}, 400)
    except CollisionError as exc:
        return json_response({"error": str(exc)}, 409)
    except StorageError as exc:
        return json_response({"error": str(exc)}, 500)

    short_url = f"{public_base_url(req)}/{link.code}"
    return json_response(
        {
            "code": link.code,
            "url": link.url,
            "short_url": short_url,
            "created_at": link.created_at,
        },
        201,
    )


@app.route(route="{code}", methods=["GET"])
def redirect_link(req: func.HttpRequest) -> func.HttpResponse:
    code = req.route_params.get("code", "")
    try:
        link = lookup_link(get_store(), code)
    except StorageError as exc:
        return json_response({"error": str(exc)}, 500)

    if link is None:
        return json_response({"error": "Short code not found"}, 404)

    # 302: temporary redirect is enough; we are not promising the mapping never changes.
    return func.HttpResponse(status_code=302, headers={"Location": link.url})
