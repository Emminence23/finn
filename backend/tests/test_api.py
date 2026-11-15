from fastapi.testclient import TestClient

from app import config


def client():
    from app.main import app

    return TestClient(app)


def test_health_reports_table_counts():
    with client() as c:
        r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["counts"]["announcements"] == 0


def test_costs_open_without_passcode_configured():
    with client() as c:
        assert c.get("/admin/costs").json() == {"total_usd": 0, "by_task": []}


def test_passcode_enforced_when_set(monkeypatch):
    monkeypatch.setenv("FINN_DEMO_PASSCODE", "s3cret")
    config.get_settings.cache_clear()
    with client() as c:
        assert c.get("/admin/costs").status_code == 401
        assert c.get("/admin/costs", headers={"X-Finn-Passcode": "s3cret"}).status_code == 200
