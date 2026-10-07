"""Only the app's own page may use it: the guard both web apps put in front of every route.

Both apps hold the monday.com token, and the alignment app writes with it — to monday.com
and to disk. Binding to 127.0.0.1 keeps out other machines, not other websites open in the
same browser, so `middleware()` adds two layers:

- **`TrustedHostMiddleware`**: the app answers only to `127.0.0.1` / `localhost` (and to the
  host given with `--host`), so another site's name pointed at this machine — DNS
  rebinding — gets nothing back to read.
- **`LocalOnlyMiddleware`**, per request (`refusal`):
  - anything the browser marks cross-site is refused, *except* following a link to a page
    (a top-level GET navigation): that only shows the user a page, and reads change nothing;
  - a POST from a foreign `Origin` is refused;
  - a POST without `HX-Request` is refused — a header a cross-site page cannot set without
    a CORS preflight, which these apps never grant. Every write goes through htmx.

So a route that changes something must be POST-only (`@app.post`): a bare `@rt` also
answers GET, and a GET is what an `<img src=…>` sends.
"""

from __future__ import annotations

import os
from typing import Any

from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse

#: The host names the apps answer to. Anything else is another site's name pointing here.
LOCAL_HOSTS = ("127.0.0.1", "localhost")

#: Bind addresses that name no host a browser would send.
WILDCARDS = ("", "0.0.0.0", "::")

#: Methods that change something. Each such route is POST-only.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def allowed_hosts() -> list[str]:
    """`LOCAL_HOSTS`, plus the address `--host` bound to (`MONDAY_HOST`, set by the CLI)."""
    extra = os.environ.get("MONDAY_HOST", "").strip()
    return [*LOCAL_HOSTS, *([extra] if extra not in WILDCARDS and extra not in LOCAL_HOSTS else [])]


def refusal(scope: Any) -> str:
    """Why this request does not come from the app's own page, in Dutch; empty when it does."""
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    method = scope.get("method", "GET")
    if headers.get("sec-fetch-site") == "cross-site":
        followed_a_link = method == "GET" and headers.get("sec-fetch-mode") == "navigate"
        if not followed_a_link:
            return "het verzoek kwam van een andere website"
    if method not in UNSAFE_METHODS:
        return ""
    origin = headers.get("origin")
    if origin and origin != f"{scope.get('scheme', 'http')}://{headers.get('host', '')}":
        return f"het verzoek kwam van {origin}"
    if headers.get("hx-request") not in ("true", "1"):  # htmx sends "true"
        return "een wijziging kan alleen vanuit de app zelf"
    return ""


class LocalOnlyMiddleware:
    """Refuses what another website sends through the user's browser — see `refusal`. A
    plain ASGI middleware, so it guards every route, present and future."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        reason = refusal(scope) if scope["type"] == "http" else ""
        if reason:
            await PlainTextResponse(f"Geweigerd: {reason}.", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def middleware() -> list[Middleware]:
    """The two layers, outermost first, for `fast_app(middleware=…)`."""
    return [
        Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts()),
        Middleware(LocalOnlyMiddleware),
    ]
