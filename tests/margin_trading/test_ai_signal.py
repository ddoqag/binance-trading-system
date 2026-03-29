"""
AIHybridSignalGenerator 测试模块。

测试 AI 混合信号生成器的完整功能，包括缓存策略、信号新鲜度、
方向映射、置信度归一化和错误处理。
"""
from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from margin_trading.ai_signal import (
    AISignal,
    AIHybridSignalGenerator,
    SignalStatus,
)


class TestAISignal:
    """AISignal dataclass 测试。"""

    def test_signal_creation(self):
        """测试 AISignal 创建。"""
        signal = AISignal(
            direction="LONG",
            confidence=0.85,
            timestamp=datetime.now(timezone.utc),
            status=SignalStatus.FRESH,
            model_consensus=0.75,
        )
        assert signal.direction == "LONG"
        assert signal.confidence == 0.85
        assert signal.status == SignalStatus.FRESH
        assert signal.model_consensus == 0.75


class TestAIHybridSignalGeneratorInitialization:
    """AIHybridSignalGenerator 初始化测试。"""

    def test_initialization_default_ttl(self):
        """test_initialization: 验证默认 TTL 配置。"""
        generator = AIHybridSignalGenerator()
        assert generator.cache_ttl == 4 * 3600  # 默认4小时
        assert generator._cache is None

    def test_initialization_custom_ttl(self):
        """测试自定义 TTL 配置。"""
        generator = AIHybridSignalGenerator(cache_ttl=7200)  # 2小时
        assert generator.cache_ttl == 7200

    def test_initialization_with_fetcher(self):
        """测试传入自定义 fetcher。"""
        mock_fetcher = MagicMock()
        generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
        assert generator.fetcher is mock_fetcher


class TestGetSignalCacheHit:
    """test_get_signal_cache_hit: 缓存命中时返回缓存信号。"""

    def test_returns_cached_signal_if_fresh(self, tmp_path: Path):
        """缓存新鲜时返回缓存信号。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            MockFetcher.return_value = mock_fetcher

            # 创建新鲜缓存
            fresh_time = datetime.now(timezone.utc).isoformat()
            mock_fetcher.get_cached_context.return_value = {
                "direction": "up",
                "confidence": 0.85,
                "regime": "bull",
                "updated_at": fresh_time,
                "model_votes": {
                    "model1": {"direction": "up", "confidence": 0.9},
                    "model2": {"direction": "up", "confidence": 0.8},
                },
            }

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal()

            assert signal.direction == "LONG"
            assert signal.confidence == 0.85
            assert signal.status == SignalStatus.FRESH
            assert signal.model_consensus == 1.0  # 2/2 一致
            mock_fetcher.fetch_async.assert_not_called()  # 不应触发异步获取


class TestGetSignalCacheExpired:
    """test_get_signal_cache_expired: 缓存过期时获取新信号。"""

    def test_fetches_new_when_expired(self, tmp_path: Path):
        """缓存过期时获取新信号。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            MockFetcher.return_value = mock_fetcher

            # 创建过期缓存（5小时前）
            expired_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            mock_fetcher.get_cached_context.return_value = {
                "direction": "up",
                "confidence": 0.85,
                "regime": "bull",
                "updated_at": expired_time,
                "model_votes": {"model1": {"direction": "up", "confidence": 0.85}},
            }

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal(symbol="BTCUSDT", price=50000.0)

            # 应该触发异步获取
            mock_fetcher.fetch_async.assert_called_once_with(
                symbol="BTCUSDT", price=50000.0, trend="neutral"
            )
            # 但返回过期缓存（因为异步还在进行中）
            assert signal.status == SignalStatus.STALE


class TestGetSignalAsyncFallback:
    """test_get_signal_async_fallback: 异步获取时使用过期缓存兜底。"""

    def test_uses_stale_cache_while_fetching_async(self):
        """异步获取时使用过期缓存作为兜底。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            MockFetcher.return_value = mock_fetcher

            # 过期缓存
            expired_time = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            mock_fetcher.get_cached_context.return_value = {
                "direction": "down",
                "confidence": 0.7,
                "regime": "bear",
                "updated_at": expired_time,
                "model_votes": {
                    "model1": {"direction": "down", "confidence": 0.8},
                    "model2": {"direction": "down", "confidence": 0.6},
                },
            }

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal(symbol="ETHUSDT", price=3000.0)

            # 应该启动异步获取
            mock_fetcher.fetch_async.assert_called_once()
            # 返回过期缓存，标记为 STALE
            assert signal.direction == "SHORT"
            assert signal.status == SignalStatus.STALE
            assert signal.model_consensus == 1.0


class TestSignalFreshnessCheck:
    """test_signal_freshness_check: 验证信号新鲜度状态判定。"""

    def test_fresh_status(self):
        """4小时内的信号为 FRESH。"""
        generator = AIHybridSignalGenerator()
        recent_time = datetime.now(timezone.utc) - timedelta(hours=2)
        status = generator._check_freshness(recent_time)
        assert status == SignalStatus.FRESH

    def test_stale_status(self):
        """超过4小时的信号为 STALE。"""
        generator = AIHybridSignalGenerator()
        old_time = datetime.now(timezone.utc) - timedelta(hours=5)
        status = generator._check_freshness(old_time)
        assert status == SignalStatus.STALE

    def test_fallback_status_for_missing_timestamp(self):
        """缺失时间戳时返回 FALLBACK。"""
        generator = AIHybridSignalGenerator()
        status = generator._check_freshness(None)
        assert status == SignalStatus.FALLBACK


class TestDirectionMapping:
    """test_direction_mapping: 测试各种 AI 响应到 LONG/SHORT/NEUTRAL 的映射。"""

    @pytest.mark.parametrize(
        "ai_direction,expected",
        [
            ("up", "LONG"),
            ("UP", "LONG"),
            ("上涨", "LONG"),
            ("看涨", "LONG"),
        ],
    )
    def test_long_direction_mapping(self, ai_direction: str, expected: str):
        """测试 LONG 方向映射。"""
        generator = AIHybridSignalGenerator()
        result = generator._map_direction(ai_direction)
        assert result == expected

    @pytest.mark.parametrize(
        "ai_direction,expected",
        [
            ("down", "SHORT"),
            ("DOWN", "SHORT"),
            ("下跌", "SHORT"),
            ("看跌", "SHORT"),
        ],
    )
    def test_short_direction_mapping(self, ai_direction: str, expected: str):
        """测试 SHORT 方向映射。"""
        generator = AIHybridSignalGenerator()
        result = generator._map_direction(ai_direction)
        assert result == expected

    @pytest.mark.parametrize(
        "ai_direction,expected",
        [
            ("sideways", "NEUTRAL"),
            ("SIDEWAYS", "NEUTRAL"),
            ("neutral", "NEUTRAL"),
            ("震荡", "NEUTRAL"),
            ("横盘", "NEUTRAL"),
            ("", "NEUTRAL"),
            ("unknown", "NEUTRAL"),
        ],
    )
    def test_neutral_direction_mapping(self, ai_direction: str, expected: str):
        """测试 NEUTRAL 方向映射。"""
        generator = AIHybridSignalGenerator()
        result = generator._map_direction(ai_direction)
        assert result == expected


class TestConfidenceNormalization:
    """test_confidence_normalization: 测试置信度归一化到 0.0-1.0。"""

    def test_confidence_within_range(self):
        """范围内的置信度保持不变。"""
        generator = AIHybridSignalGenerator()
        assert generator._normalize_confidence(0.85) == 0.85
        assert generator._normalize_confidence(0.0) == 0.0
        assert generator._normalize_confidence(1.0) == 1.0

    def test_confidence_clamping_high(self):
        """>1.0 的置信度被截断到 1.0。"""
        generator = AIHybridSignalGenerator()
        assert generator._normalize_confidence(1.5) == 1.0
        assert generator._normalize_confidence(2.0) == 1.0

    def test_confidence_clamping_low(self):
        """<0.0 的置信度被截断到 0.0。"""
        generator = AIHybridSignalGenerator()
        assert generator._normalize_confidence(-0.5) == 0.0
        assert generator._normalize_confidence(-1.0) == 0.0

    def test_confidence_default_for_invalid(self):
        """无效值使用默认置信度 0.5。"""
        generator = AIHybridSignalGenerator()
        assert generator._normalize_confidence(None) == 0.5
        assert generator._normalize_confidence("invalid") == 0.5


class TestErrorHandling:
    """test_error_handling: 测试错误时的优雅降级。"""

    def test_graceful_fallback_on_fetcher_error(self):
        """fetcher 错误时返回默认信号。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.get_cached_context.side_effect = Exception("Connection error")
            MockFetcher.return_value = mock_fetcher

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal()

            assert signal.direction == "NEUTRAL"
            assert signal.confidence == 0.5
            assert signal.status == SignalStatus.ERROR
            assert signal.model_consensus == 0.0

    def test_graceful_fallback_on_invalid_context(self):
        """无效上下文时返回默认信号。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            mock_fetcher.get_cached_context.return_value = {
                "direction": None,
                "confidence": None,
                "regime": None,
                "updated_at": None,
                "model_votes": {},
            }
            MockFetcher.return_value = mock_fetcher

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal()

            assert signal.direction == "NEUTRAL"
            assert signal.confidence == 0.5
            assert signal.status == SignalStatus.FALLBACK


class TestModelConsensusCalculation:
    """test_model_consensus_calculation: 测试模型一致性比例计算。"""

    def test_full_consensus(self):
        """所有模型一致时 consensus = 1.0。"""
        generator = AIHybridSignalGenerator()
        model_votes = {
            "model1": {"direction": "up", "confidence": 0.9},
            "model2": {"direction": "up", "confidence": 0.8},
            "model3": {"direction": "up", "confidence": 0.85},
        }
        consensus = generator._calculate_consensus(model_votes, "up")
        assert consensus == 1.0

    def test_partial_consensus(self):
        """部分一致时正确计算比例。"""
        generator = AIHybridSignalGenerator()
        model_votes = {
            "model1": {"direction": "up", "confidence": 0.9},
            "model2": {"direction": "up", "confidence": 0.8},
            "model3": {"direction": "down", "confidence": 0.7},
        }
        consensus = generator._calculate_consensus(model_votes, "up")
        assert consensus == 2 / 3

    def test_no_consensus(self):
        """无一致时 consensus = 0.0。"""
        generator = AIHybridSignalGenerator()
        model_votes = {
            "model1": {"direction": "down", "confidence": 0.9},
            "model2": {"direction": "sideways", "confidence": 0.8},
            "model3": {"direction": "down", "confidence": 0.7},
        }
        consensus = generator._calculate_consensus(model_votes, "up")
        assert consensus == 0.0

    def test_empty_votes(self):
        """空投票时 consensus = 0.0。"""
        generator = AIHybridSignalGenerator()
        consensus = generator._calculate_consensus({}, "up")
        assert consensus == 0.0


class TestIntegration:
    """集成测试。"""

    def test_full_signal_generation_flow(self):
        """测试完整信号生成流程。"""
        with patch("margin_trading.ai_signal.AIContextFetcher") as MockFetcher:
            mock_fetcher = MagicMock()
            MockFetcher.return_value = mock_fetcher

            fresh_time = datetime.now(timezone.utc).isoformat()
            mock_fetcher.get_cached_context.return_value = {
                "direction": "down",
                "confidence": 0.75,
                "regime": "bear",
                "updated_at": fresh_time,
                "model_votes": {
                    "Doubao": {"direction": "down", "confidence": 0.8},
                    "Yuanbao": {"direction": "down", "confidence": 0.7},
                    "ChatGPT": {"direction": "sideways", "confidence": 0.6},
                },
            }

            generator = AIHybridSignalGenerator(fetcher=mock_fetcher)
            signal = generator.get_signal()

            assert signal.direction == "SHORT"
            assert signal.confidence == 0.75
            assert signal.status == SignalStatus.FRESH
            # 2/3 模型同意 down
            assert signal.model_consensus == pytest.approx(2 / 3, rel=1e-3)
