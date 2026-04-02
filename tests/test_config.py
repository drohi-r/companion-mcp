import os
import pytest
from unittest.mock import patch

from companion_mcp.config import CompanionConfig, load_config, _parse_port


def test_default_config():
    config = CompanionConfig()
    assert config.host == "127.0.0.1"
    assert config.port == 8000
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


def test_load_config_from_env():
    with patch.dict(os.environ, {"COMPANION_HOST": "192.168.1.50", "COMPANION_PORT": "9090"}):
        config = load_config()
    assert config.host == "192.168.1.50"
    assert config.port == 9090
