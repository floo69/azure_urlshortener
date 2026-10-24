"""Core URL-shortener logic. No HTTP and no Azure Functions code lives here.

Storage is behind a tiny interface so tests can use memory and production can
use Azure Table Storage without changing create/lookup logic.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol
from urllib.parse import urlparse


# Base62: digits + upper + lower. URL-safe, no lookalike padding like base64 "+" "/".
CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CODE_LENGTH = 7
# 62^7 is huge; a few retries are enough unless the table is extremely full.
MAX_COLLISION_RETRIES = 5
MAX_URL_LENGTH = 2048

# Route names used by function_app.py. GET /links would otherwise look like a code.
RESERVED_CODES = frozenset({"links"})

# One partition for all links. See AzureTableStore for why.
TABLE_PARTITION_KEY = "link"


class InvalidURLError(ValueError):
    """The long URL failed validation."""


class CollisionError(RuntimeError):
    """Could not allocate a unique short code after retries."""


class StorageError(RuntimeError):
    """The storage backend failed (network, permissions, etc.)."""


@dataclass(frozen=True)
class Link:
    code: str
    url: str
    created_at: str  # ISO-8601 UTC


class LinkStore(Protocol):
    """Minimal storage interface used by the core functions."""

    def get(self, code: str) -> Optional[Link]:
        """Return the link or None if the code is unknown."""

    def save(self, link: Link) -> bool:
        """Create the link. Return False if that code already exists (do not overwrite)."""


class InMemoryStore:
    """Dict-backed store for unit tests and local runs with STORAGE_BACKEND=memory."""

    def __init__(self) -> None:
        self._links: dict[str, Link] = {}

    def get(self, code: str) -> Optional[Link]:
        return self._links.get(code)

    def save(self, link: Link) -> bool:
        if link.code in self._links:
            return False
        self._links[link.code] = link
        return True


def validate_url(url: str) -> str:
    """Accept only http(s) URLs with a host, within a sane length."""
    if not isinstance(url, str):
        raise InvalidURLError("URL must be a string")

    cleaned = url.strip()
    if not cleaned:
        raise InvalidURLError("URL is empty")
    if len(cleaned) > MAX_URL_LENGTH:
        raise InvalidURLError(f"URL is longer than {MAX_URL_LENGTH} characters")
    if any(ch.isspace() for ch in cleaned):
        raise InvalidURLError("URL must not contain whitespace")

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError("URL must start with http:// or https://")
    if not parsed.netloc:
        raise InvalidURLError("URL must include a host")
    # netloc can be "user:pass@host"; still a valid URL, but reject empty host edge cases.
    host = parsed.hostname
    if not host:
        raise InvalidURLError("URL must include a host")

    return cleaned


def generate_code(length: int = CODE_LENGTH) -> str:
    # secrets.choice is cryptographically strong, so codes are hard to guess.
    # random.choice would be weaker and easier to brute-force.
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def is_reserved_code(code: str) -> bool:
    return code.lower() in RESERVED_CODES


def is_valid_code_format(code: str) -> bool:
    """Lookup only accepts the exact shape we generate (avoids treating /links as a code)."""
    if not isinstance(code, str) or len(code) != CODE_LENGTH:
        return False
    return all(ch in CODE_ALPHABET for ch in code)


def create_short_link(store: LinkStore, url: str) -> Link:
    """Validate, generate a unique code, and save. Retries on collision."""
    cleaned = validate_url(url)
    created_at = datetime.now(timezone.utc).isoformat()

    for _ in range(MAX_COLLISION_RETRIES):
        code = generate_code()
        if is_reserved_code(code):
            # Almost impossible with length 7, but keep the rule absolute.
            continue
        link = Link(code=code, url=cleaned, created_at=created_at)
        try:
            saved = store.save(link)
        except StorageError:
            raise
        except Exception as exc:  # backend-specific errors get a single type for HTTP
            raise StorageError("failed to save link") from exc
        if saved:
            return link

    raise CollisionError(
        f"could not allocate a unique short code after {MAX_COLLISION_RETRIES} retries"
    )


def lookup_link(store: LinkStore, code: str) -> Optional[Link]:
    """Return a stored link, or None for reserved / badly shaped / missing codes."""
    if is_reserved_code(code) or not is_valid_code_format(code):
        return None
    try:
        return store.get(code)
    except StorageError:
        raise
    except Exception as exc:
        raise StorageError("failed to look up link") from exc


class AzureTableStore:
    """Azure Table Storage adapter. Lazy-imports the SDK so unit tests need not install it.

    PartitionKey = "link" (constant):
        Table Storage scales by partition. This app does point lookups, not large
        scans, so one partition keeps get/save simple: we always know the partition.

    RowKey = short code:
        RowKey is unique inside a partition. The code is already our unique id,
        so PartitionKey + RowKey maps 1:1 to a short link.
        create_entity() is create-only: if that pair exists, Azure raises and we
        do not overwrite the original URL.
    """

    def __init__(self, connection_string: str, table_name: str) -> None:
        if not connection_string:
            raise StorageError("STORAGE_CONNECTION_STRING is missing")
        if not table_name:
            raise StorageError("TABLE_NAME is missing")

        from azure.data.tables import TableServiceClient

        service = TableServiceClient.from_connection_string(connection_string)
        # Safe if you already created the table in the portal; no-op when it exists.
        service.create_table_if_not_exists(table_name)
        self._table = service.get_table_client(table_name)

    def get(self, code: str) -> Optional[Link]:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            entity = self._table.get_entity(
                partition_key=TABLE_PARTITION_KEY, row_key=code
            )
        except ResourceNotFoundError:
            return None
        except Exception as exc:
            raise StorageError("Azure Table read failed") from exc

        return Link(
            code=entity["RowKey"],
            url=entity["Url"],
            created_at=entity["CreatedAt"],
        )

    def save(self, link: Link) -> bool:
        from azure.core.exceptions import ResourceExistsError

        entity = {
            "PartitionKey": TABLE_PARTITION_KEY,
            "RowKey": link.code,
            "Url": link.url,
            "CreatedAt": link.created_at,
        }
        try:
            # create_entity = insert only. update_entity/upsert_entity would overwrite.
            self._table.create_entity(entity)
            return True
        except ResourceExistsError:
            return False
        except Exception as exc:
            raise StorageError("Azure Table write failed") from exc
