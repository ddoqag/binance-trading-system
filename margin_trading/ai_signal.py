"""
AI 混合信号生成器。

提供基于 AI 市场分析的交易信号生成，支持缓存优先策略、
信号新鲜度检查、异步后台更新和优雅降级。

集成 trading_system.ai_context 模块，使用 AIContextFetcher
获取多模型市场分析结果。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from trading_system.ai_context import AIContextFetcher

logger = logging.getLogger(__name__)


class SignalStatus(Enum):
    """信号状态枚举。"""

    FRESH = "fresh"  # 新鲜信号（缓存有效期内）
    STALE = "stale"  # 过期信号（缓存过期但仍可用）
    FALLBACK = "fallback"  # 兜底信号（使用默认值）
    ERROR = "error"  # 错误状态（获取失败）


@dataclass(frozen=True)
class AISignal:
    """
    AI 交易信号数据类。

    Attributes:
        direction: 交易方向 ('LONG', 'SHORT', 'NEUTRAL')
        confidence: 置信度 (0.0-1.0)
        timestamp: 信号时间戳
        status: 信号状态
        model_consensus: 模型一致性比例 (0.0-1.0)
    """

    direction: str
    confidence: float
    timestamp: datetime
    status: SignalStatus
    model_consensus: float


class AIHybridSignalGenerator:
    """
    AI 混合信号生成器。

    实现缓存优先策略：
    1. 首先检查缓存，如果新鲜直接返回
    2. 如果缓存过期，启动异步获取并返回过期缓存
    3. 如果没有缓存，返回兜底信号

    Attributes:
        cache_ttl: 缓存有效期（秒），默认 4 小时
        min_confidence: 最小置信度阈值
        fetcher: AIContextFetcher 实例
    """

    # 默认缓存有效期：4 小时
    DEFAULT_CACHE_TTL = 4 * 3600

    # 默认最小置信度
    DEFAULT_MIN_CONFIDENCE = 0.6

    # 方向映射：AI 响应 -> 交易信号
    DIRECTION_MAP = {
        # 英文映射
        "up": "LONG",
        "down": "SHORT",
        "sideways": "NEUTRAL",
        "neutral": "NEUTRAL",
        # 中文映射
        "上涨": "LONG",
        "下跌": "SHORT",
        "震荡": "NEUTRAL",
        "横盘": "NEUTRAL",
        "看涨": "LONG",
        "看跌": "SHORT",
    }

    def __init__(
        self,
        cache_ttl: Optional[int] = None,
        min_confidence: Optional[float] = None,
        fetcher: Optional[AIContextFetcher] = None,
    ):
        """
        初始化信号生成器。

        Args:
            cache_ttl: 缓存有效期（秒），默认 4 小时 (14400)
            min_confidence: 最小置信度阈值，默认 0.6
            fetcher: 可选的 AIContextFetcher 实例
        """
        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.min_confidence = min_confidence or self.DEFAULT_MIN_CONFIDENCE
        self.fetcher = fetcher or AIContextFetcher()
        self._cache: Optional[dict] = None  # symbol -> signal dict
        self._last_context: Optional[dict] = None
        self._cache_file: str = "market_context.json"
        self._fetcher: AIContextFetcher = self.fetcher  # Alias for compatibility

    def get_signal(
        self,
        symbol: str = "BTCUSDT",
        price: float = 0.0,
        trend: str = "neutral",
        **kwargs,
    ) -> AISignal:
        """
        获取 AI 交易信号。

        缓存优先策略：
        1. 尝试获取缓存的上下文
        2. 如果缓存新鲜，直接转换为信号返回
        3. 如果缓存过期，启动异步获取并返回过期信号
        4. 如果发生错误，返回兜底信号

        Args:
            symbol: 交易对符号
            price: 当前价格
            trend: 当前趋势描述
            **kwargs: 额外参数（用于 future 扩展）

        Returns:
            AISignal: 交易信号
        """
        try:
            # 获取缓存的上下文
            context = self.fetcher.get_cached_context()
            self._last_context = context

            # 检查时间戳
            updated_at = context.get("updated_at")
            timestamp = self._parse_timestamp(updated_at)

            # 确定信号新鲜度
            status = self._check_freshness(timestamp)

            # 如果缓存过期或不存在，启动异步获取
            if status in (SignalStatus.STALE, SignalStatus.FALLBACK):
                logger.debug("AI 缓存过期或不存在，启动异步获取")
                self.fetcher.fetch_async(
                    symbol=symbol,
                    price=price,
                    trend=trend,
                )

            # 构建信号（即使过期也使用缓存）
            signal = self._build_signal(context, status, timestamp)
            self._cache = signal
            return signal

        except Exception as exc:
            logger.error("获取 AI 信号失败: %s", exc)
            return self._create_error_signal()

    def _build_signal(
        self,
        context: dict,
        status: SignalStatus,
        timestamp: Optional[datetime],
    ) -> AISignal:
        """
        从 AI 上下文构建信号。

        Args:
            context: AI 上下文字典
            status: 信号状态
            timestamp: 时间戳

        Returns:
            AISignal: 交易信号
        """
        # 提取原始方向并映射
        raw_direction = context.get("direction", "sideways")
        direction = self._map_direction(raw_direction)

        # 归一化置信度
        raw_confidence = context.get("confidence", 0.5)
        confidence = self._normalize_confidence(raw_confidence)

        # 计算模型一致性
        model_votes = context.get("model_votes", {})
        consensus = self._calculate_consensus(model_votes, raw_direction)

        # 使用当前时间如果 timestamp 为 None
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        return AISignal(
            direction=direction,
            confidence=confidence,
            timestamp=timestamp,
            status=status,
            model_consensus=consensus,
        )

    def _map_direction(self, ai_direction: Optional[str]) -> str:
        """
        将 AI 方向映射到交易信号方向。

        Args:
            ai_direction: AI 返回的方向字符串

        Returns:
            str: 'LONG', 'SHORT', 或 'NEUTRAL'
        """
        if ai_direction is None:
            return "NEUTRAL"

        normalized = str(ai_direction).lower()
        return self.DIRECTION_MAP.get(normalized, "NEUTRAL")

    def _normalize_confidence(self, confidence: Optional[float]) -> float:
        """
        归一化置信度到 0.0-1.0 范围。

        Args:
            confidence: 原始置信度值

        Returns:
            float: 归一化后的置信度 (0.0-1.0)
        """
        if confidence is None:
            return 0.5

        try:
            conf = float(confidence)
            return max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            return 0.5

    def _check_freshness(self, timestamp: Optional[datetime]) -> SignalStatus:
        """
        检查信号新鲜度。

        Args:
            timestamp: 信号时间戳

        Returns:
            SignalStatus: 信号状态
        """
        if timestamp is None:
            return SignalStatus.FALLBACK

        age_seconds = (datetime.now(timezone.utc) - timestamp).total_seconds()

        if age_seconds <= self.cache_ttl:
            return SignalStatus.FRESH
        else:
            return SignalStatus.STALE

    def _calculate_consensus(
        self,
        model_votes: dict,
        target_direction: str,
    ) -> float:
        """
        计算模型一致性比例。

        Args:
            model_votes: 模型投票字典
            target_direction: 目标方向

        Returns:
            float: 一致性比例 (0.0-1.0)
        """
        if not model_votes:
            return 0.0

        total = len(model_votes)
        agreeing = sum(
            1
            for vote in model_votes.values()
            if vote.get("direction", "").lower() == target_direction.lower()
        )

        return agreeing / total

    def _parse_timestamp(self, updated_at: Optional[str]) -> Optional[datetime]:
        """
        解析时间戳字符串。

        Args:
            updated_at: ISO 格式时间戳字符串

        Returns:
            Optional[datetime]: 解析后的时间戳或 None
        """
        if updated_at is None:
            return None

        try:
            # 处理带 Z 的 ISO 格式
            timestamp_str = str(updated_at).replace("Z", "+00:00")
            return datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            return None

    def _create_error_signal(self) -> AISignal:
        """
        创建错误状态的兜底信号。

        Returns:
            AISignal: 错误信号
        """
        return AISignal(
            direction="NEUTRAL",
            confidence=0.5,
            timestamp=datetime.now(timezone.utc),
            status=SignalStatus.ERROR,
            model_consensus=0.0,
        )

    def get_last_context(self) -> Optional[dict]:
        """
        获取最后一次获取的原始 AI 上下文。

        Returns:
            Optional[dict]: 原始上下文字典
        """
        return self._last_context

    def clear_cache(self) -> None:
        """清除内部缓存。"""
        self._cache = {}
        self._last_context = None

    # =========================================================================
    # Task-required API methods
    # =========================================================================

    def generate_signal(self, symbol: str, force_refresh: bool = False) -> dict:
        """
        Generate trading signal for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            force_refresh: If True, bypass cache and fetch new signal

        Returns:
            Dict with signal information:
            {
                'symbol': str,
                'direction': str ('LONG', 'SHORT', 'NEUTRAL'),
                'confidence': float (0.0-1.0),
                'timestamp': float (unix timestamp),
                'status': SignalStatus,
                'model_consensus': float (0.0-1.0)
            }
        """
        try:
            # Check cache first (unless force_refresh)
            if not force_refresh:
                cached = self.get_cached_signal(symbol)
                if cached is not None:
                    return cached

            # Fetch new signal from AI context
            context = self.fetcher.get_cached_context()
            self._last_context = context

            # Build signal from context
            signal = self._build_signal_from_context(symbol, context)

            # Cache the signal
            self._cache[symbol] = signal
            self._save_cache()

            return signal

        except Exception as exc:
            logger.error("Failed to generate signal for %s: %s", symbol, exc)
            return self._create_error_signal_dict(symbol)

    def get_cached_signal(self, symbol: str) -> Optional[dict]:
        """
        Get cached signal if valid.

        Args:
            symbol: Trading pair symbol

        Returns:
            Cached signal dict or None if not found or expired
        """
        if symbol not in self._cache:
            # Try to load from file
            self._load_cache()

        if symbol not in self._cache:
            return None

        signal = self._cache[symbol]

        # Check if expired
        if not self.is_cache_valid(symbol):
            return None

        return signal

    def is_cache_valid(self, symbol: str) -> bool:
        """
        Check if cache is still valid for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            True if cache exists and is within TTL
        """
        if symbol not in self._cache:
            return False

        signal = self._cache[symbol]
        timestamp = signal.get('timestamp', 0)
        age_seconds = time.time() - timestamp

        return age_seconds < self.cache_ttl

    def invalidate_cache(self, symbol: str) -> None:
        """
        Invalidate cache for a symbol.

        Args:
            symbol: Trading pair symbol to invalidate
        """
        if symbol in self._cache:
            del self._cache[symbol]
            self._save_cache()

    def calculate_hybrid_confidence(self, ai_context: dict) -> float:
        """
        Calculate hybrid confidence from AI models.

        Uses majority vote agreement ratio. If models disagree significantly,
        reduces confidence by 30%.

        Args:
            ai_context: AI context dict with 'model_votes' key

        Returns:
            Hybrid confidence score (0.0-1.0)
        """
        model_votes = ai_context.get('model_votes', {})
        base_confidence = ai_context.get('confidence', 0.5)

        if not model_votes:
            return self._normalize_confidence(base_confidence)

        # Count votes by direction
        direction_counts = {}
        for vote in model_votes.values():
            direction = vote.get('direction', 'sideways').lower()
            direction_counts[direction] = direction_counts.get(direction, 0) + 1

        total_votes = len(model_votes)
        max_votes = max(direction_counts.values())
        agreement_ratio = max_votes / total_votes

        # Determine majority direction
        majority_direction = max(direction_counts, key=direction_counts.get)

        # Calculate average confidence for majority direction
        majority_confidences = [
            vote.get('confidence', 0.5)
            for vote in model_votes.values()
            if vote.get('direction', '').lower() == majority_direction
        ]
        avg_confidence = sum(majority_confidences) / len(majority_confidences) if majority_confidences else 0.5

        # If models disagree (no absolute majority), reduce confidence by 30%
        if agreement_ratio < 0.5:
            avg_confidence *= 0.7

        return self._normalize_confidence(avg_confidence)

    def get_direction(self, ai_context: dict) -> str:
        """
        Get trading direction from AI context.

        Args:
            ai_context: AI context dict with 'model_votes' or 'direction' key

        Returns:
            Direction string: 'LONG', 'SHORT', or 'NEUTRAL'
        """
        model_votes = ai_context.get('model_votes', {})

        if not model_votes:
            # Fall back to direct direction field
            raw_direction = ai_context.get('direction', 'sideways')
            return self._map_direction(raw_direction)

        # Count votes by direction
        direction_counts = {}
        for vote in model_votes.values():
            direction = vote.get('direction', 'sideways').lower()
            direction_counts[direction] = direction_counts.get(direction, 0) + 1

        if not direction_counts:
            return 'NEUTRAL'

        # Find majority direction
        majority_direction = max(direction_counts, key=direction_counts.get)

        return self._map_direction(majority_direction)

    # =========================================================================
    # Private helper methods
    # =========================================================================

    def _build_signal_from_context(self, symbol: str, context: dict) -> dict:
        """Build signal dict from AI context."""
        direction = self.get_direction(context)
        confidence = self.calculate_hybrid_confidence(context)

        # Calculate model consensus
        model_votes = context.get('model_votes', {})
        raw_direction = context.get('direction', 'sideways')
        consensus = self._calculate_consensus_dict(model_votes, raw_direction)

        # Determine status based on freshness
        updated_at = context.get('updated_at')
        timestamp = time.time()
        if updated_at:
            try:
                dt = datetime.fromisoformat(str(updated_at).replace('Z', '+00:00'))
                timestamp = dt.timestamp()
            except (ValueError, TypeError):
                pass

        age_seconds = time.time() - timestamp
        if age_seconds > self.cache_ttl:
            status = SignalStatus.STALE
        else:
            status = SignalStatus.FRESH

        return {
            'symbol': symbol,
            'direction': direction,
            'confidence': confidence,
            'timestamp': timestamp,
            'status': status,
            'model_consensus': consensus
        }

    def _calculate_consensus_dict(self, model_votes: dict, target_direction: str) -> float:
        """Calculate consensus ratio for dict-based signals."""
        if not model_votes:
            return 0.0

        total = len(model_votes)
        agreeing = sum(
            1
            for vote in model_votes.values()
            if vote.get("direction", "").lower() == target_direction.lower()
        )

        return agreeing / total

    def _create_error_signal_dict(self, symbol: str) -> dict:
        """Create error signal as dict."""
        return {
            'symbol': symbol,
            'direction': 'NEUTRAL',
            'confidence': 0.5,
            'timestamp': time.time(),
            'status': SignalStatus.ERROR,
            'model_consensus': 0.0
        }

    def _check_signal_freshness(self, signal: dict) -> tuple[bool, float]:
        """
        Check signal freshness.

        Args:
            signal: Signal dict with 'timestamp' key

        Returns:
            Tuple of (is_fresh: bool, age_seconds: float)
        """
        timestamp = signal.get('timestamp', 0)
        age_seconds = time.time() - timestamp
        is_fresh = age_seconds < self.cache_ttl
        return is_fresh, age_seconds

    def _save_cache(self) -> None:
        """Save cache to file."""
        try:
            with open(self._cache_file, 'w', encoding='utf-8') as f:
                # Convert SignalStatus to string for JSON serialization
                cache_copy = {}
                for symbol, signal in self._cache.items():
                    signal_copy = signal.copy()
                    if isinstance(signal_copy.get('status'), SignalStatus):
                        signal_copy['status'] = signal_copy['status'].value
                    cache_copy[symbol] = signal_copy
                json.dump(cache_copy, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            logger.warning("Failed to save cache: %s", exc)

    def _load_cache(self) -> None:
        """Load cache from file."""
        try:
            if Path(self._cache_file).exists():
                with open(self._cache_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    # Convert status strings back to SignalStatus
                    for symbol, signal in loaded.items():
                        status_str = signal.get('status', 'fallback')
                        if isinstance(status_str, str):
                            try:
                                signal['status'] = SignalStatus(status_str)
                            except ValueError:
                                signal['status'] = SignalStatus.FALLBACK
                        self._cache[symbol] = signal
        except Exception as exc:
            logger.warning("Failed to load cache: %s", exc)
            self._cache = {}
