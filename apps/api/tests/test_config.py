import pytest

from app import config


PLACEHOLDERS = [(name, value) for name, values in config.INSECURE_VALUES.items() for value in values]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.mark.parametrize("name,value", PLACEHOLDERS)
def test_get_settings_refuses_a_published_placeholder_secret(monkeypatch, name, value):
    monkeypatch.setenv(name.upper(), value)
    with pytest.raises(RuntimeError, match=name.upper()):
        config.get_settings()


def test_get_settings_reports_every_unchanged_secret_at_once(monkeypatch):
    for name, values in config.INSECURE_VALUES.items():
        monkeypatch.setenv(name.upper(), values[0])
    with pytest.raises(RuntimeError) as excinfo:
        config.get_settings()
    for name in config.INSECURE_VALUES:
        assert name.upper() in str(excinfo.value)


def test_get_settings_accepts_real_secrets(monkeypatch):
    for name in config.INSECURE_VALUES:
        monkeypatch.setenv(name.upper(), f"a-real-value-for-{name}")
    settings = config.get_settings()
    assert settings.secret_key == "a-real-value-for-secret_key"
