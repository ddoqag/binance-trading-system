#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场趋势分析器 - 使用AI模型分析市场趋势
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging
from pathlib import Path


class TrendType(Enum):
    """趋势类型"""
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"


class MarketRegime(Enum):
    """市场状态"""
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"
    HIGH_VOLATILITY = "high_volatility"


class MarketAnalyzer:
    """市场趋势分析器"""

    def __init__(self, model_path: Optional[str] = None):
        """
        初始化市场分析器

        Args:
            model_path: AI模型路径，None则使用基于规则的分析
        """
        self.logger = logging.getLogger('MarketAnalyzer')
        self.model_path = model_path
        self.model = None
        self.tokenizer = None

        # 如果提供了模型路径，尝试加载模型
        if model_path and Path(model_path).exists():
            self._load_model(model_path)

    def _load_model(self, model_path: str):
        """加载AI模型"""
        try:
            # 尝试使用 transformers 加载模型
            from transformers import AutoModelForCausalLM, AutoTokenizer
            self.logger.info(f"Loading model from {model_path}")
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                model_path,
                trust_remote_code=True,
                device_map="auto"
            )
            self.logger.info("Model loaded successfully")
        except Exception as e:
            self.logger.warning(f"Failed to load model: {e}, will use rule-based analysis")
            self.model = None
            self.tokenizer = None

    def analyze_trend(self, df: pd.DataFrame) -> Dict[str, any]:
        """
        分析市场趋势

        Args:
            df: K线数据，包含 open, high, low, close, volume

        Returns:
            趋势分析结果字典
        """
        if len(df) < 20:
            return {
                'trend': TrendType.SIDEWAYS,
                'regime': MarketRegime.NEUTRAL,
                'confidence': 0.5,
                'analysis': 'Insufficient data'
            }

        # 基于规则的分析
        result = self._rule_based_analysis(df)

        # 如果有本地 AI 模型，使用 AI 进行增强分析
        if self.model is not None:
            ai_analysis = self._ai_enhanced_analysis(df)
            result.update(ai_analysis)

        # 读取 ai-compare.exe 后台查询缓存（免费多模型投票，替代 Kimi API）
        result = self._apply_ai_context(result, df)

        return result

    def _rule_based_analysis(self, df: pd.DataFrame) -> Dict[str, any]:
        """基于规则的趋势分析"""
        close_prices = df['close'].values
        volumes = df['volume'].values

        # 计算价格趋势
        short_ma = close_prices[-10:].mean()
        long_ma = close_prices[-30:].mean()
        current_price = close_prices[-1]

        # 计算波动率
        returns = np.diff(np.log(close_prices))
        volatility = returns[-20:].std() * np.sqrt(365)

        # 确定趋势类型
        if current_price > short_ma > long_ma:
            trend = TrendType.UPTREND
            regime = MarketRegime.BULL
        elif current_price < short_ma < long_ma:
            trend = TrendType.DOWNTREND
            regime = MarketRegime.BEAR
        elif volatility > 0.05:
            trend = TrendType.VOLATILE
            regime = MarketRegime.HIGH_VOLATILITY
        else:
            trend = TrendType.SIDEWAYS
            regime = MarketRegime.NEUTRAL

        # 计算趋势强度（置信度）
        momentum = (current_price - long_ma) / long_ma
        confidence = min(0.9, 0.5 + abs(momentum))

        # 成交量分析
        avg_volume = volumes[-30:].mean()
        recent_volume = volumes[-5:].mean()
        volume_trend = recent_volume / avg_volume if avg_volume > 0 else 1.0

        # 支撑阻力位
        support = df['low'][-30:].min()
        resistance = df['high'][-30:].max()

        return {
            'trend': trend,
            'regime': regime,
            'confidence': confidence,
            'current_price': current_price,
            'short_ma': short_ma,
            'long_ma': long_ma,
            'volatility': volatility,
            'volume_trend': volume_trend,
            'support_level': support,
            'resistance_level': resistance,
            'momentum': momentum
        }

    def _apply_ai_context(self, result: dict, df: pd.DataFrame) -> dict:
        """
        读取 ai-compare.exe 的后台查询缓存，将多模型投票结论融合到规则分析结果中。

        融合规则：
          - AI 方向与规则方向一致 → confidence × 1.1（上限 0.95）
          - AI 方向与规则方向相反 → confidence × 0.85（打折）
          - AI regime 与规则不同   → 输出警告，保留规则 regime
          - 缓存不可用            → 原样返回 result（无影响）
        """
        try:
            from trading_system.ai_context import get_cached_context
            ctx = get_cached_context()
        except Exception:
            return result

        if not ctx.get("updated_at"):
            return result  # 没有有效缓存

        # 规则方向 → 字符串
        trend = result.get("trend")
        rule_dir = (
            "up" if trend == TrendType.UPTREND else
            "down" if trend == TrendType.DOWNTREND else
            "sideways"
        )

        ai_dir = ctx.get("direction", "sideways")
        ai_conf = float(ctx.get("confidence", 0.5))
        orig_conf = float(result.get("confidence", 0.5))

        if ai_dir == rule_dir:
            new_conf = min(0.95, orig_conf * 1.1)
        elif ai_dir != "sideways" and rule_dir != "sideways":
            # 方向相反
            new_conf = orig_conf * 0.85
        else:
            new_conf = orig_conf  # 一方 sideways → 不调整

        result["confidence"] = round(new_conf, 3)
        result["ai_context"] = {
            "direction": ai_dir,
            "confidence": ai_conf,
            "regime": ctx.get("regime"),
            "risk": ctx.get("risk"),
            "model_count": len(ctx.get("model_votes", {})),
        }
        self.logger.debug(
            "AI 上下文融合：rule_dir=%s ai_dir=%s conf %.3f→%.3f",
            rule_dir, ai_dir, orig_conf, new_conf,
        )
        return result

    def _ai_enhanced_analysis(self, df: pd.DataFrame) -> Dict[str, any]:
        """AI增强的趋势分析（本地 Qwen/transformers 模型）"""
        try:
            # 准备市场数据摘要
            summary = self._prepare_market_summary(df)

            # 构建提示词
            prompt = self._build_analysis_prompt(summary)

            # 使用模型生成分析
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=500,
                temperature=0.7,
                do_sample=True
            )
            analysis_text = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

            # 解析AI分析结果
            return {
                'ai_analysis': analysis_text,
                'ai_enhanced': True
            }
        except Exception as e:
            self.logger.warning(f"AI analysis failed: {e}")
            return {'ai_enhanced': False}

    def _prepare_market_summary(self, df: pd.DataFrame) -> Dict[str, any]:
        """准备市场数据摘要"""
        close = df['close'].values
        return {
            'price_change_24h': (close[-1] - close[-24]) / close[-24] if len(close) > 24 else 0,
            'price_change_7d': (close[-1] - close[-168]) / close[-168] if len(close) > 168 else 0,
            'current_price': close[-1],
            'high_24h': df['high'][-24:].max(),
            'low_24h': df['low'][-24:].min(),
            'avg_volume': df['volume'][-24:].mean()
        }

    def _build_analysis_prompt(self, summary: Dict[str, any]) -> str:
        """构建分析提示词"""
        return f"""你是一个专业的加密货币市场分析师。请分析以下市场数据并提供趋势判断：

当前市场数据：
- 当前价格: ${summary['current_price']:.2f}
- 24小时涨跌幅: {summary['price_change_24h']*100:.2f}%
- 7天涨跌幅: {summary['price_change_7d']*100:.2f}%
- 24小时最高: ${summary['high_24h']:.2f}
- 24小时最低: ${summary['low_24h']:.2f}
- 平均成交量: {summary['avg_volume']:.0f}

请提供：
1. 市场趋势判断（上涨/下跌/震荡）
2. 风险评估
3. 操作建议

分析：
"""

    def get_suitable_strategies(self, trend_analysis: Dict[str, any]) -> List[str]:
        """
        根据趋势分析获取适合的策略列表

        Args:
            trend_analysis: 趋势分析结果

        Returns:
            适合的策略名称列表
        """
        trend = trend_analysis.get('trend')
        regime = trend_analysis.get('regime')
        volatility = trend_analysis.get('volatility', 0)

        strategies = []

        # 根据趋势匹配策略
        if trend == TrendType.UPTREND:
            strategies.extend(['dual_ma', 'momentum', 'trend_following'])
        elif trend == TrendType.DOWNTREND:
            strategies.extend(['rsi', 'mean_reversion', 'trend_following'])
        elif trend == TrendType.SIDEWAYS:
            strategies.extend(['mean_reversion', 'rsi', 'grid_trading'])
        elif trend == TrendType.VOLATILE:
            strategies.extend(['rsi', 'volatility_arbitrage', 'options_strategy'])

        # 根据波动率调整
        if volatility > 0.08:
            strategies.append('risk_control_overlay')
        elif volatility < 0.02:
            strategies.append('momentum_enhanced')

        return strategies
