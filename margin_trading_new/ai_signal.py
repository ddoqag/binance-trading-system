"""
AI 混合信号生成器。

提供基于 AI 市场分析的交易信号生成，支持缓存优先策略、
信号新鲜度检查、异步后台更新和优雅降级。

集成 trading_system.ai_context 模块，使用 AIContextFetcher
获取多模型市场分析结果。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
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
        fetcher: AIContextFetcher 实例
    """

    # 默认缓存有效期：4 小时
    DEFAULT_CACHE_TTL = 4 * 3600

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
        fetcher: Optional[AIContextFetcher] = None,
    ):
        """
        初始化信号生成器。

        Args:
            cache_ttl: 缓存有效期（秒），默认 4 小时
            fetcher: 可选的 AIContextFetcher 实例
        """
        self.cache_ttl = cache_ttl or self.DEFAULT_CACHE_TTL
        self.fetcher = fetcher or AIContextFetcher()
        self._cache: Optional[AISignal] = None
        self._last_context: Optional[dict] = None

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
        self._cache = None
        self._last_context = None
