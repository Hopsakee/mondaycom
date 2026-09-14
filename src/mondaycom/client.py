"""Thin HTTP client for the monday.com GraphQL API.

The API answers with HTTP 200 even when the query failed, so every response goes
through :meth:`MondayClient.execute`, which raises on the ``errors`` key instead
of handing back a dict that silently has no ``data``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from mondaycom.config import API_URL, API_VERSION, api_key


class MondayError(RuntimeError):
    """A GraphQL error returned by monday.com, or a transport failure."""


class MondayClient:
    """Session-backed client for `POST https://api.monday.com/v2`."""

    def __init__(
        self,
        token: str | None = None,
        api_url: str = API_URL,
        api_version: str = API_VERSION,
        timeout: float = 30.0,
    ) -> None:
        self.api_url = api_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": token or api_key(),
                "API-Version": api_version,
                "Content-Type": "application/json",
            }
        )

    def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a query or mutation and return its ``data`` payload."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = self.session.post(self.api_url, json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise MondayError(f"HTTP {response.status_code} from monday.com: {response.text[:500]}")

        body = response.json()
        if errors := body.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in errors)
            raise MondayError(f"monday.com rejected the query: {messages}")
        if body.get("error_message"):
            raise MondayError(f"monday.com returned an error: {body['error_message']}")

        data: dict[str, Any] | None = body.get("data")
        if data is None:
            raise MondayError(f"monday.com returned no data: {body}")
        return data

    def board_items(self, query: str) -> list[dict[str, Any]]:
        """Run an ``items_page`` query and return the items of the first board."""
        data = self.execute(query)
        boards = data.get("boards") or []
        if not boards:
            return []
        items: list[dict[str, Any]] = boards[0]["items_page"]["items"]
        return items

    def all_board_items(self, build: Callable[[str | None], str]) -> list[dict[str, Any]]:
        """Follow ``items_page`` pagination to the end and return every item.

        You cannot ask a board for all its items in one go: `items_page` caps at 500 and
        hands back a `cursor` for the next slice. `build` takes that cursor (``None`` for
        the first call) and returns the query to run — see `queries.board_tasks`.
        """
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            data = self.execute(build(cursor))
            boards = data.get("boards") or []
            if not boards:
                return items
            page = boards[0]["items_page"]
            items.extend(page["items"])
            cursor = page.get("cursor")
            if not cursor:
                return items

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> MondayClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
