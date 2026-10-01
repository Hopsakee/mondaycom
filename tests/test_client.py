"""Offline tests for the GraphQL client's sessions. No network: nothing is posted."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from mondaycom.client import MondayClient


def other_threads_session(client: MondayClient) -> object:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: client.session).result()


def test_a_thread_keeps_its_session_and_another_thread_gets_its_own() -> None:
    """A `requests.Session` is not thread-safe, so one client hands one to each thread."""
    client = MondayClient(token="t")
    assert client.session is client.session
    other = other_threads_session(client)
    assert other is not client.session
    assert other.headers["Authorization"] == client.session.headers["Authorization"] == "t"  # type: ignore[attr-defined]


def test_every_threads_session_shares_one_connection_pool() -> None:
    """So a connection outlives the thread that opened it — web worker threads retire
    after ten idle seconds, and `fetch_epics` reads on short-lived pool threads."""
    client = MondayClient(token="t")
    other = other_threads_session(client)
    assert client.session.get_adapter("https://api.monday.com/v2") is client.adapter
    assert other.get_adapter("https://api.monday.com/v2") is client.adapter  # type: ignore[attr-defined]
