import os
import pytest
from unittest.mock import patch

from companion_mcp.config import CompanionConfig, load_config, _parse_port
from companion_mcp.config import _parse_timeout, _parse_allowed_hosts


def test_default_config():
    config = CompanionConfig()
    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert config.timeout_s == 10.0
    assert config.base_url == "http://127.0.0.1:8000"


def test_custom_config():
    config = CompanionConfig(host="10.0.0.5", port=9000)
    assert config.base_url == "http://10.0.0.5:9000"


def test_parse_port_valid():
    assert _parse_port("TEST_PORT", "8000") == 8000


def test_parse_port_rejects_non_integer():
    with patch.dict(os.environ, {"TEST_PORT": "abc"}):
        with pytest.raises(ValueError, match="not a valid integer"):
            _parse_port("TEST_PORT", "8000")


def test_parse_port_rejects_out_of_range():
    with patch.dict(os.environ, {"TEST_PORT": "99999"}):
        with pytest.raises(ValueError, match="outside valid port range"):
            _parse_port("TEST_PORT", "8000")


def test_load_config_defaults():
    config = load_config()
    assert config.host == "127.0.0.1"
    assert config.port == 8000
    assert "127.0.0.1" in config.allowed_hosts


def test_load_config_from_env():
    with patch.dict(
        os.environ,
        {
            "COMPANION_HOST": "192.168.1.50",
            "COMPANION_PORT": "9090",
            "COMPANION_TIMEOUT_S": "2.5",
            "COMPANION_ALLOWED_HOSTS": "127.0.0.1,192.168.1.50",
        },
    ):
        config = load_config()
    assert config.host == "192.168.1.50"
    assert config.port == 9090
    assert config.timeout_s == 2.5
    assert config.allowed_hosts == ("127.0.0.1", "192.168.1.50")


def test_parse_timeout_valid():
    assert _parse_timeout("TEST_TIMEOUT", "10.0") == 10.0


def test_parse_timeout_rejects_non_numeric():
    with patch.dict(os.environ, {"TEST_TIMEOUT": "fast"}):
        with pytest.raises(ValueError, match="not a valid number"):
            _parse_timeout("TEST_TIMEOUT", "10.0")


def test_parse_timeout_rejects_non_positive():
    with patch.dict(os.environ, {"TEST_TIMEOUT": "0"}):
        with pytest.raises(ValueError, match="must be > 0"):
            _parse_timeout("TEST_TIMEOUT", "10.0")


def test_parse_allowed_hosts():
    with patch.dict(os.environ, {"TEST_ALLOWED_HOSTS": "127.0.0.1, companion.local"}):
        assert _parse_allowed_hosts("TEST_ALLOWED_HOSTS", "") == ("127.0.0.1", "companion.local")


def test_load_config_rejects_disallowed_host():
    with patch.dict(
        os.environ,
        {
            "COMPANION_HOST": "10.0.0.10",
            "COMPANION_ALLOWED_HOSTS": "127.0.0.1,localhost",
        },
    ):
        with pytest.raises(ValueError, match="not allowed"):
            load_config()
