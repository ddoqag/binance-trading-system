"""
Configuration management module - 配置管理模块
"""

from config.settings import Settings, get_settings, DBConfig, TradingConfig
from config.config_manager import ConfigManager, load_config
from config.atomic_updater import AtomicConfigUpdater, ConfigValidator, UpdateResult, RollbackResult

# API 端点配置
try:
    from config.api_config import (
        API_BASE_URLS,
        MARKET_DATA_ENDPOINTS,
        TRADE_ENDPOINTS,
        ORDER_LIST_ENDPOINTS,
        ACCOUNT_ENDPOINTS,
        PRICE_EXECUTION_ENDPOINTS,
        USER_STREAM_ENDPOINTS,
        RATE_LIMIT_ENDPOINTS,
        API_ENDPOINTS,
        COMMON_ENDPOINTS,
        HttpMethods,
        ENDPOINT_METHODS,
        ENDPOINTS_REQUIRE_SIGNATURE
    )
    API_CONFIG_AVAILABLE = True
except ImportError:
    API_CONFIG_AVAILABLE = False

__all__ = [
    "Settings",
    "get_settings",
    "DBConfig",
    "TradingConfig",
    "ConfigManager",
    "load_config",
    "AtomicConfigUpdater",
    "ConfigValidator",
    "UpdateResult",
    "RollbackResult"
]

if API_CONFIG_AVAILABLE:
    __all__ += [
        "API_BASE_URLS",
        "MARKET_DATA_ENDPOINTS",
        "TRADE_ENDPOINTS",
        "ORDER_LIST_ENDPOINTS",
        "ACCOUNT_ENDPOINTS",
        "PRICE_EXECUTION_ENDPOINTS",
        "USER_STREAM_ENDPOINTS",
        "RATE_LIMIT_ENDPOINTS",
        "API_ENDPOINTS",
        "COMMON_ENDPOINTS",
        "HttpMethods",
        "ENDPOINT_METHODS",
        "ENDPOINTS_REQUIRE_SIGNATURE"
    ]
