"""
Settings management - Python 配置管理
使用环境变量加载敏感配置
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DBConfig:
    """数据库配置"""
    host: str = "localhost"
    port: int = 5432
    database: str = "binance"
    user: str = "postgres"
    password: str = ""

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password": self.password,
        }


@dataclass
class QwenConfig:
    """Qwen3.5-7B 模型配置"""
    model_path: str = "D:/binance/models/Qwen/Qwen3-8B"
    auto_download: bool = False
    quantization: str = "none"  # none, 4bit, 8bit
    max_tokens: int = 500
    temperature: float = 0.7
    device: str = "auto"

    @classmethod
    def from_env(cls) -> 'QwenConfig':
        """从环境变量加载配置"""
        import os
        return cls(
            model_path=os.environ.get("QWEN_MODEL_PATH", cls.model_path),
            auto_download=os.environ.get("QWEN_AUTO_DOWNLOAD", "false").lower() == "true",
            quantization=os.environ.get("QWEN_QUANTIZATION", cls.quantization),
            max_tokens=int(os.environ.get("QWEN_MAX_TOKENS", str(cls.max_tokens))),
            temperature=float(os.environ.get("QWEN_TEMPERATURE", str(cls.temperature)))
        )


@dataclass
class TradingConfig:
    """Trading configuration"""
    initial_capital: float = 10000.0
    max_position_size: float = 0.8  # 80% of total capital
    max_single_position: float = 0.2  # 20% per strategy
    commission_rate: float = 0.001  # 0.1%
    symbol: str = "BTCUSDT"
    interval: str = "1h"

    # Strategy parameters
    strategy_type: str = "DualMA"
    short_window: int = 12
    long_window: int = 25

    @property
    def interval_seconds(self) -> int:
        """Convert interval string to seconds"""
        interval_map = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "6h": 21600,
            "8h": 28800,
            "12h": 43200,
            "1d": 86400,
            "3d": 259200,
            "1w": 604800,
            "1M": 2592000
        }
        return interval_map.get(self.interval, 3600)  # Default to 1 hour


class Settings:
    """应用配置"""

    def __init__(self, env_file: Optional[Path] = None):
        """
        初始化配置

        Args:
            env_file: .env 文件路径，默认从项目根目录加载
        """
        self._load_env(env_file)
        self.db = self._load_db_config()
        self.trading = self._load_trading_config()
        self.qwen = QwenConfig.from_env()

    def _load_env(self, env_file: Optional[Path] = None) -> None:
        """加载环境变量"""
        if env_file is None:
            env_file = Path(__file__).parent.parent / ".env"

        if env_file.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file)
            except ImportError:
                # 如果没有 python-dotenv，手动加载
                with open(env_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            os.environ[key.strip()] = value.strip()

    def _load_db_config(self) -> DBConfig:
        """加载数据库配置"""
        return DBConfig(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            database=os.environ.get("DB_NAME", "binance"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
        )

    def _load_trading_config(self) -> TradingConfig:
        """加载交易配置"""
        return TradingConfig(
            initial_capital=float(os.environ.get("INITIAL_CAPITAL", "10000")),
            max_position_size=float(os.environ.get("MAX_POSITION_SIZE", "0.8")),
            max_single_position=float(os.environ.get("MAX_SINGLE_POSITION", "0.2")),
            commission_rate=float(os.environ.get("COMMISSION_RATE", "0.001")),
            symbol=os.environ.get("DEFAULT_SYMBOL", "BTCUSDT"),
            interval=os.environ.get("DEFAULT_INTERVAL", "1h"),
        )


# 全局配置单例
_settings_instance: Optional[Settings] = None


def get_settings(env_file: Optional[Path] = None) -> Settings:
    """
    获取全局配置实例（单例模式）

    Args:
        env_file: .env 文件路径

    Returns:
        Settings 配置实例
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings(env_file)
    return _settings_instance
