#!/usr/bin/env python3
"""helpers.py 模块的单元测试"""

import sys
sys.path.insert(0, 'D:/binance')

import logging
from pathlib import Path
import pytest

# 直接从文件导入，避免 utils/__init__.py 的依赖问题
from utils.helpers import (
    setup_logger,
    get_timestamp,
    safe_float,
    parse_bool,
)


class TestSetupLogger:
    """测试 setup_logger 函数"""

    def test_default_logger_creation(self):
        logger = setup_logger("test_default")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_default"
        assert logger.level == logging.INFO

    def test_custom_level(self):
        logger = setup_logger("test_debug", level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_no_file_handler(self):
        logger = setup_logger("test_no_file", log_file=None)
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 0


class TestGetTimestamp:
    """测试 get_timestamp 函数"""

    def test_utc_timestamp_format(self):
        timestamp = get_timestamp(utc=True)
        assert "T" in timestamp
        assert "+" in timestamp or "Z" in timestamp

    def test_local_timestamp_format(self):
        timestamp = get_timestamp(utc=False)
        assert "T" in timestamp


class TestSafeFloat:
    """测试 safe_float 函数"""

    def test_valid_string(self):
        assert safe_float("123.45") == 123.45
        assert safe_float("-99.5") == -99.5

    def test_valid_integer(self):
        assert safe_float(100) == 100.0
        assert safe_float(-50) == -50.0

    def test_none_value(self):
        assert safe_float(None) == 0.0
        assert safe_float(None, default=5.0) == 5.0

    def test_invalid_string(self):
        assert safe_float("abc") == 0.0
        assert safe_float("") == 0.0

    def test_min_max_constraints(self):
        assert safe_float("150", min_value=0, max_value=100) == 100.0
        assert safe_float("-50", min_value=0, max_value=100) == 0.0


class TestParseBool:
    """测试 parse_bool 函数"""

    def test_true_values(self):
        true_values = [True, 1, "true", "yes", "1", "on"]
        for val in true_values:
            assert parse_bool(val) is True, f"Expected True for {val!r}"

    def test_false_values(self):
        false_values = [False, 0, "false", "no", "0", "off", ""]
        for val in false_values:
            assert parse_bool(val) is False, f"Expected False for {val!r}"

    def test_none_with_default(self):
        assert parse_bool(None, default=True) is True
        assert parse_bool(None, default=False) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
