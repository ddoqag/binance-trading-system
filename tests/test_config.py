#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for config module
测试配置模块
"""

import pytest
import os
from pathlib import Path
from unittest.mock import patch, mock_open


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary .env file for testing"""
    env_content = """
DB_HOST=test-host
DB_PORT=5433
DB_NAME=test_db
DB_USER=test_user
DB_PASSWORD=test_password
INITIAL_CAPITAL=50000
MAX_POSITION_SIZE=0.5
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_content)
    return env_file


class TestDBConfig:
    """Tests for DBConfig dataclass"""

    def test_db_config_defaults(self):
        """Test DBConfig default values"""
        from config.settings import DBConfig
        config = DBConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "binance"
        assert config.user == "postgres"
        assert config.password == ""

    def test_db_config_custom(self):
        """Test DBConfig with custom values"""
        from config.settings import DBConfig
        config = DBConfig(
            host="custom-host",
            port=1234,
            database="custom-db",
            user="custom-user",
            password="custom-pass"
        )
        assert config.host == "custom-host"
        assert config.port == 1234
        assert config.database == "custom-db"
        assert config.user == "custom-user"
        assert config.password == "custom-pass"

    def test_db_config_to_dict(self):
        """Test DBConfig to_dict method"""
        from config.settings import DBConfig
        config = DBConfig(
            host="my-host",
            port=9999,
            database="my-db",
            user="my-user",
            password="my-pass"
        )
        d = config.to_dict()
        assert isinstance(d, dict)
        assert d["host"] == "my-host"
        assert d["port"] == 9999
        assert d["database"] == "my-db"
        assert d["user"] == "my-user"
        assert d["password"] == "my-pass"


class TestTradingConfig:
    """Tests for TradingConfig dataclass"""

    def test_trading_config_defaults(self):
        """Test TradingConfig default values"""
        from config.settings import TradingConfig
        config = TradingConfig()
        assert config.initial_capital == 10000.0
        assert config.max_position_size == 0.8
        assert config.max_single_position == 0.2
        assert config.commission_rate == 0.001
        assert config.symbol == "BTCUSDT"
        assert config.interval == "1h"


class TestSettings:
    """Tests for Settings class"""

    def test_settings_defaults(self):
        """Test Settings with default values (no env file)"""
        from config.settings import Settings
        settings = Settings(env_file=Path("/nonexistent/.env"))
        assert settings.db.host == "localhost"
        assert settings.db.port == 5432
        assert settings.trading.initial_capital == 10000.0

    def test_settings_from_env_file(self, temp_env_file, monkeypatch):
        """Test Settings loads from env file"""
        from config.settings import Settings
        # Clear any env vars loaded by earlier tests so the temp file wins
        for key in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                    "INITIAL_CAPITAL", "MAX_POSITION_SIZE"]:
            monkeypatch.delenv(key, raising=False)
        settings = Settings(env_file=temp_env_file)
        assert settings.db.host == "test-host"
        assert settings.db.port == 5433
        assert settings.db.database == "test_db"
        assert settings.db.user == "test_user"
        assert settings.db.password == "test_password"
        assert settings.trading.initial_capital == 50000.0
        assert settings.trading.max_position_size == 0.5

    def test_settings_from_env_vars(self):
        """Test Settings loads from environment variables"""
        from config.settings import Settings
        with patch.dict(os.environ, {
            "DB_HOST": "env-host",
            "DB_PORT": "6666",
            "DB_NAME": "env-db",
            "DB_USER": "env-user",
            "DB_PASSWORD": "env-pass",
        }):
            settings = Settings(env_file=Path("/nonexistent/.env"))
            assert settings.db.host == "env-host"
            assert settings.db.port == 6666
            assert settings.db.database == "env-db"
            assert settings.db.user == "env-user"
            assert settings.db.password == "env-pass"


class TestGetSettings:
    """Tests for get_settings singleton"""

    def test_get_settings_returns_same_instance(self):
        """Test get_settings returns the same instance (singleton)"""
        from config.settings import get_settings, _settings_instance

        # Reset singleton for test
        import config.settings
        config.settings._settings_instance = None

        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_get_settings_with_env_file(self, temp_env_file, monkeypatch):
        """Test get_settings with custom env file"""
        from config.settings import get_settings

        # Reset singleton for test
        import config.settings
        config.settings._settings_instance = None

        # Clear any env vars loaded by earlier tests so the temp file wins
        for key in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
                    "INITIAL_CAPITAL", "MAX_POSITION_SIZE"]:
            monkeypatch.delenv(key, raising=False)

        settings = get_settings(env_file=temp_env_file)
        assert settings.db.host == "test-host"
        assert settings.db.password == "test_password"


class TestConfigModuleImport:
    """Tests for config module imports"""

    def test_import_config(self):
        """Test importing config module"""
        import config
        assert hasattr(config, "settings")

    def test_import_settings(self):
        """Test importing from config.settings"""
        from config import settings
        assert hasattr(settings, "get_settings")
        assert hasattr(settings, "DBConfig")
        assert hasattr(settings, "TradingConfig")
        assert hasattr(settings, "Settings")
