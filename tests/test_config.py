import pytest
from src.common.config import load_config


def test_scale_and_environment(monkeypatch):
    monkeypatch.setenv("SCALE", "full")
    monkeypatch.setenv("REDIS_HOST", "localhost")
    monkeypatch.setenv("REDIS_PORT", "6380")
    cfg = load_config()
    assert [cfg["simulator"][k] for k in ("n_products", "n_users", "n_events")] == [50000, 10000, 1000000]
    assert cfg["redis"] == {"host": "localhost", "port": 6380}
    monkeypatch.setenv("SCALE", "dev")
    assert load_config()["simulator"]["n_products"] == 10000


def test_invalid_scale_and_port(monkeypatch):
    monkeypatch.setenv("SCALE", "wrong")
    with pytest.raises(ValueError, match="SCALE"):
        load_config()
    monkeypatch.setenv("SCALE", "dev")
    monkeypatch.setenv("REDIS_PORT", "70000")
    with pytest.raises(ValueError, match="PORT"):
        load_config()


def test_load_isolation(monkeypatch):
    monkeypatch.delenv("SCALE", raising=False)
    original = load_config()
    changed = load_config()
    changed["search"]["faiss"]["M"] = 99
    assert load_config() == original
