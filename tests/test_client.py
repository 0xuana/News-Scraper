import httpx
import pytest

from collector.aigupiao.client import AccessDenied, AigupiaoClient, RetriesExhausted


def test_client_ignores_ambient_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:10808")

    with AigupiaoClient("https://example.test"):
        pass


def test_client_retries_429_using_retry_after() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"rslt": "succ", "data": {}})

    client = AigupiaoClient(
        "https://example.test", transport=httpx.MockTransport(handler), sleep=sleeps.append
    )

    assert client.fetch()["rslt"] == "succ"
    assert calls == 2
    assert sleeps == [7.0]


def test_client_retries_5xx_then_exhausts() -> None:
    sleeps: list[float] = []
    transport = httpx.MockTransport(lambda request: httpx.Response(503))
    client = AigupiaoClient(
        "https://example.test",
        max_retries=2,
        transport=transport,
        sleep=sleeps.append,
    )

    with pytest.raises(RetriesExhausted):
        client.fetch()

    assert sleeps == [5.0, 10.0]


def test_client_does_not_retry_403() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403))
    client = AigupiaoClient("https://example.test", transport=transport)

    with pytest.raises(AccessDenied):
        client.fetch()


def test_client_retries_malformed_json() -> None:
    sleeps: list[float] = []
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"not json")
    )
    client = AigupiaoClient(
        "https://example.test",
        max_retries=1,
        transport=transport,
        sleep=sleeps.append,
    )

    with pytest.raises(RetriesExhausted):
        client.fetch()

    assert sleeps == [5.0]
