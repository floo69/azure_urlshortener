"""Hit a deployed (or local) Function: create a link, follow the 302, check the target.

Usage:
  python tests/smoke_test.py https://YOUR-FUNCTION.azurewebsites.net
  SMOKE_BASE_URL=https://YOUR-FUNCTION.azurewebsites.net python tests/smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

TARGET_URL = "https://example.com/"


def base_url() -> str:
    arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SMOKE_BASE_URL", "")
    arg = arg.strip().rstrip("/")
    if not arg:
        print("Pass the Function base URL as an argument or set SMOKE_BASE_URL.", file=sys.stderr)
        sys.exit(2)
    return arg


def request(url: str, data: Optional[bytes] = None, method: str = "GET", follow: bool = True):
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    # context=None uses default HTTPS verification.
    opener = urllib.request.build_opener(
        urllib.request.HTTPRedirectHandler() if follow else urllib.request.HTTPHandler()
    )
    if not follow:
        # Do not follow redirects so we can assert status 302 and Location.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(NoRedirect)
    return opener.open(req, timeout=30)


def main() -> int:
    root = base_url()
    create_url = f"{root}/links"
    body = json.dumps({"url": TARGET_URL}).encode("utf-8")

    try:
        with request(create_url, data=body, method="POST", follow=True) as resp:
            status = resp.status
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(f"CREATE failed: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')}")
        return 1
    except Exception as exc:
        print(f"CREATE failed: {exc}")
        return 1

    if status != 201:
        print(f"CREATE expected 201, got {status}: {payload}")
        return 1
    for key in ("code", "url", "short_url", "created_at"):
        if key not in payload:
            print(f"CREATE missing field {key}: {payload}")
            return 1
    if payload["url"] != TARGET_URL:
        print(f"CREATE stored wrong URL: {payload['url']}")
        return 1

    short_url = payload["short_url"]
    print(f"Created {short_url}")

    try:
        # HTTPError is raised for 302 when we refuse to follow, on some Python builds;
        # handle both.
        try:
            resp = request(short_url, method="GET", follow=False)
            redir_status = resp.status
            location = resp.headers.get("Location")
            resp.close()
        except urllib.error.HTTPError as exc:
            redir_status = exc.code
            location = exc.headers.get("Location")
    except Exception as exc:
        print(f"REDIRECT failed: {exc}")
        return 1

    if redir_status not in (301, 302, 303, 307, 308):
        print(f"REDIRECT expected 302, got {redir_status}")
        return 1
    if location != TARGET_URL:
        print(f"REDIRECT Location expected {TARGET_URL}, got {location}")
        return 1

    print(f"Redirect {redir_status} -> {location}")
    print("Smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
