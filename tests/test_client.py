"""Offline tests for the GraphQL client's sessions. No network: nothing is posted."""

from __future__ import annotations

import gc
from concurrent.futures import ThreadPoolExecutor

from mondaycom.client import MondayClient


def test_a_thread_keeps_its_session_and_another_thread_gets_its_own() -> None:
    """A `requests.Session` is not thread-safe, so one client hands one to each thread."""
    client = MondayClient(token="t")
    assert client.session is client.session, "kept, so its connection pool survives"
    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(lambda: client.session).result()
    assert other is not client.session
    assert other.headers["Authorization"] == client.session.headers["Authorization"] == "t"


def test_close_closes_every_threads_session_and_the_next_call_opens_a_fresh_one() -> None:
    client = MondayClient(token="t")
    first = client.session
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(lambda: client.session).result()
    client.close()
    assert len(client._sessions) == 0
    assert client.session is not first


def test_a_finished_threads_session_is_not_kept_alive_by_the_client() -> None:
    """`fetch_epics` reads on short-lived pool threads; a long-lived client must not hoard them."""
    client = MondayClient(token="t")
    for _ in range(3):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: client.session).result()
    gc.collect()
    assert len(client._sessions) == 0
