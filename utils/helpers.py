#!/usr/bin/env python3
"""
工具函数模块 - 提供日志、时间戳和类型转换等通用工具函数
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


__all__ = [
    "setup_logger",
    "get_timestamp",
    "safe_float",
    "parse_bool",
]


def setup_logger(
    name: str = "binance_trading",
    level: int = logging.INFO,
    log_file: str | Path | None = "trading.log",
    log_format: str | None = None,
    date_format: str | None = None,
    handlers: Sequence[logging.Handler] | None = None,
) -> logging.Logger:
    """设置并配置日志记录器。

    支持控制台和文件输出，可自定义格式和级别。

    Args:
        name: 日志器名称，用于区分不同模块的日志
        level: 日志级别，默认为 INFO
        log_file: 日志文件路径，设为 None 则不输出到文件
        log_format: 自定义日志格式，None 使用默认格式
        date_format: 自定义日期格式，None 使用默认格式
        handlers: 预定义的 handlers，提供时将忽略默认配置

    Returns:
        配置好的 Logger 实例

    Example:
        >>> logger = setup_logger("my_app", level=logging.DEBUG)
        >>> logger.info("应用启动成功")
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 清理现有 handlers 避免重复添加
    logger.handlers.clear()

    # 使用用户提供的 handlers
    if handlers:
        for handler in handlers:
            logger.addHandler(handler)
        return logger

    # 设置默认格式
    _log_format = log_format or "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    _date_format = date_format or "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(_log_format, datefmt=_date_format)

    # 控制台输出 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出 handler（仅在指定了文件路径时）
    if log_file:
        file_path = Path(log_file)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_timestamp(utc: bool = True) -> str:
    """获取当前时间戳字符串。

    Args:
        utc: 是否使用 UTC 时间，默认为 True

    Returns:
        ISO 8601 格式的时间戳字符串

    Example:
        >>> ts = get_timestamp()
        >>> print(ts)  # 2024-01-15T08:30:00+00:00
    """
    if utc:
        return datetime.now(timezone.utc).isoformat()
    return datetime.now().astimezone().isoformat()


def safe_float(
    value: str | int | float | None,
    default: float = 0.0,
    allow_nan: bool = False,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    """安全地将值转换为 float 类型。

    处理各种输入类型，提供默认值和范围限制功能。

    Args:
        value: 待转换的值，支持 str/int/float/None
        default: 转换失败时的默认值
        allow_nan: 是否允许 NaN 作为有效值
        min_value: 最小值限制（包含）
        max_value: 最大值限制（包含）

    Returns:
        转换后的 float 值，或默认值

    Example:
        >>> safe_float("123.45")  # 123.45
        >>> safe_float(None, default=1.0)  # 1.0
        >>> safe_float("invalid", default=-1.0)  # -1.0
        >>> safe_float("150", min_value=0, max_value=100)  # 100.0
    """
    if value is None:
        return default

    try:
        result = float(value)
    except (ValueError, TypeError):
        return default

    # 检查 NaN
    if not allow_nan and math.isnan(result):
        return default

    # 应用范围限制
    if min_value is not None and result < min_value:
        result = min_value
    if max_value is not None and result > max_value:
        result = max_value

    return result


def parse_bool(value: str | int | bool | None, default: bool = False) -> bool:
    """安全地将值解析为 bool 类型。

    处理字符串、整数和 None 值，识别常见的真假值表示。

    Args:
        value: 待解析的值
        default: 无法解析时的默认值

    Returns:
        解析后的 bool 值

    Example:
        >>> parse_bool("true")  # True
        >>> parse_bool("no")  # False
        >>> parse_bool(1)  # True
        >>> parse_bool(None, default=True)  # True
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value != 0

    # 字符串解析
    if isinstance(value, str):
        true_values = {"true", "yes", "1", "on", "enabled", "y"}
        false_values = {"false", "no", "0", "off", "disabled", "n", ""}

        lower_val = value.lower().strip()
        if lower_val in true_values:
            return True
        if lower_val in false_values:
            return False

    return default
