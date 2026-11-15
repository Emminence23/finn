import time

import httpx

from app.http import Fetcher, RateLimiter


def test_rate_limiter_spaces_requests_per_host():
    rl = RateLimiter(0.2)
    t0 = time.monotonic()
    rl.wait("a.com")
    rl.wait("b.com")  # different host: no wait
    rl.wait("a.com")  # same host: waits ~0.2s
    assert 0.18 <= time.monotonic() - t0 < 0.5


def test_fetcher_caches_responses(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, json={"n": len(calls)})

    f = Fetcher(cache_dir=tmp_path, min_interval=0)
    f.client = httpx.Client(transport=httpx.MockTransport(handler))
    assert f.get_json("https://example.com/x", params={"a": 1}) == {"n": 1}
    assert f.get_json("https://example.com/x", params={"a": 1}) == {"n": 1}  # cached
    assert f.get_json("https://example.com/x", params={"a": 2}) == {"n": 2}
    assert len(calls) == 2
