"""Unit tests for core logic. Uses InMemoryStore so no Azure account is required."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Azure Functions runs with api/ as the working directory; tests do the same for imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from shortener import (  # noqa: E402
    CODE_ALPHABET,
    CODE_LENGTH,
    CollisionError,
    InMemoryStore,
    InvalidURLError,
    Link,
    create_short_link,
    generate_code,
    lookup_link,
    validate_url,
)


def test_valid_https_url_is_accepted():
    assert validate_url("  https://example.com/path  ") == "https://example.com/path"


def test_valid_http_url_is_accepted():
    assert validate_url("http://localhost:8080/page") == "http://localhost:8080/page"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "example.com",
        "ftp://example.com",
        "javascript:alert(1)",
        "https://",
        "https:///nohost",
        "https://example.com/has space",
        "a" * 3000,
    ],
)
def test_invalid_urls_are_rejected(bad):
    with pytest.raises(InvalidURLError):
        validate_url(bad)


def test_generated_code_is_base62_and_fixed_length():
    code = generate_code()
    assert len(code) == CODE_LENGTH
    assert all(ch in CODE_ALPHABET for ch in code)


def test_create_and_lookup_hit():
    store = InMemoryStore()
    link = create_short_link(store, "https://example.com/article")
    found = lookup_link(store, link.code)
    assert found is not None
    assert found.url == "https://example.com/article"
    assert found.code == link.code
    assert found.created_at


def test_lookup_miss_returns_none():
    store = InMemoryStore()
    assert lookup_link(store, "abcdefg") is None


def test_reserved_code_is_never_looked_up():
    store = InMemoryStore()
    # Even if storage somehow had this row, lookup must refuse the route name.
    store.save(Link(code="links", url="https://example.com", created_at="t"))
    assert lookup_link(store, "links") is None


def test_create_skips_reserved_generated_codes():
    store = InMemoryStore()
    # First "random" value is the reserved route name; second is a real code.
    with patch(
        "shortener.generate_code",
        side_effect=["links", "AbC123x"],
    ):
        link = create_short_link(store, "https://example.com")
    assert link.code == "AbC123x"
    assert lookup_link(store, "AbC123x") is not None


def test_codes_are_unique_for_two_saves():
    store = InMemoryStore()
    first = create_short_link(store, "https://example.com/one")
    second = create_short_link(store, "https://example.com/two")
    assert first.code != second.code


def test_collision_retries_then_succeeds():
    store = InMemoryStore()
    store.save(Link(code="taken01", url="https://example.com/old", created_at="t"))

    with patch("shortener.generate_code", side_effect=["taken01", "fresh01"]):
        link = create_short_link(store, "https://example.com/new")
    assert link.code == "fresh01"
    assert lookup_link(store, "taken01").url == "https://example.com/old"


def test_collision_retries_exhausted_raises():
    store = InMemoryStore()
    store.save(Link(code="same001", url="https://example.com/old", created_at="t"))

    with patch("shortener.generate_code", return_value="same001"):
        with pytest.raises(CollisionError):
            create_short_link(store, "https://example.com/new")
