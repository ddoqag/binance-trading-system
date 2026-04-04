"""
实时数据驱动的自优化交易系统

结合 autoresearch 理念和实时市场数据：
1. 使用真实市场数据而非回测
2. 实时监控策略表现
3. 根据市场反馈动态调整参数
4. 24/7持续优化
"""

import asyncio
import json
import time
import yaml
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
import threading


@dataclass
class StrategyPerformance:
    """策略实时表现"""
    strategy_name: str
    signal_count: int = 0
    correct_predictions: int = 0
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    last_updated: float = 0.0


@dataclass
class MarketRegime:
    """市场状态"""
    regime: str  # trending, ranging, volatile, mixed
    confidence: float
    volatility: float
    trend_strength: float
    timestamp: float


class LiveAutoResearch:
    """
    实时自优化交易系统

    核心特性：
    1. 实时数据流：连接交易所WebSocket
    2. 在线学习：根据实时表现调整权重
    3. 参数热更新：无需重启即可调整参数
    4. 自适应评估：根据市场状态动态调整评估标准
    """

    def __init__(self):
        self.config_file = 'config/signal_evaluation.yaml'
        self.performance_window = 100  # 保留最近100个表现数据
        self.regime_window = 50  # 市场状态窗口

        # 实时数据缓存
        self.price_history: deque = deque(maxlen=500)
        self.strategy_performances: Dict[str, StrategyPerformance] = {}
        self.regime_history: deque = deque(maxlen=self.regime_window)
        self.weight_history: deque = deque(maxlen=200)

        # 当前配置
        self.current_config = self._load_config()

        # 优化状态
        self.optimization_active = False
        self.last_optimization = 0
        self.optimization_interval = 300  # 每5分钟优化一次

        # 性能跟踪
        self.metrics = {
            'total_updates': 0,
            'optimization_count': 0,
            'regime_transitions': 0,
            'avg_stability': 0.0
        }

    def _load_config(self) -> Dict:
        """加载配置"""
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f)
        except:
            return self._default_config()

    def _save_config(self, config: Dict):
        """保存配置"""
        with open(self.config_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)

    def _default_config(self) -> Dict:
        """默认配置"""
        return {
            'signal_scoring': {
                'weights': {'accuracy': 0.35, 'consistency': 0.40, 'strength': 0.25},
                'decay_lambda': 0.8,
                'max_single_weight': 0.60,
                'min_single_weight': 0.05,
                'exploration_noise': 0.05
            }
        }

    def update_price(self, price: float, timestamp: Optional[float] = None):
        """更新实时价格"""
        if timestamp is None:
            timestamp = time.time()

        self.price_history.append({
            'price': price,
            'timestamp': timestamp
        })

        # 检测市场状态
        self._detect_regime()

    def _detect_regime(self):
        """检测当前市场状态"""
        if len(self.price_history) < 50:
            return

        prices = [p['price'] for p in self.price_history]
        returns = np.diff(prices) / prices[:-1]

        # 计算波动率
        volatility = np.std(returns[-20:]) * np.sqrt(365 * 24 * 12)  # 年化

        # 计算趋势强度
        if len(prices) >= 20:
            ma_short = np.mean(prices[-10:])
            ma_long = np.mean(prices[-20:])
            trend_strength = abs(ma_short - ma_long) / ma_long
        else:
            trend_strength = 0

        # 判断市场状态
        if volatility > 0.5:  # 高波动
            regime = 'volatile'
            confidence = min(1.0, volatility)
        elif trend_strength > 0.02:  # 强趋势
            regime = 'trending'
            confidence = min(1.0, trend_strength * 10)
        elif volatility < 0.2:  # 低波动
            regime = 'ranging'
            confidence = 1.0 - volatility / 0.2
        else:
            regime = 'mixed'
            confidence = 0.5

        new_regime = MarketRegime(
            regime=regime,
            confidence=confidence,
            volatility=volatility,
            trend_strength=trend_strength,
            timestamp=time.time()
        )

        # 检查状态转换
        if self.regime_history:
            last_regime = self.regime_history[-1]
            if last_regime.regime != regime:
                self.metrics['regime_transitions'] += 1
                self._on_regime_change(last_regime, new_regime)

        self.regime_history.append(new_regime)

    def _on_regime_change(self, old: MarketRegime, new: MarketRegime):
        """市场状态转换时的处理"""
        print(f"[{datetime.now()}] Regime change: {old.regime} -> {new.regime} "
              f"(confidence: {new.confidence:.2f})")

        # 根据新状态调整评估参数
        self._adapt_to_regime(new.regime)

    def _adapt_to_regime(self, regime: str):
        """根据市场状态自适应调整参数"""
        config = self.current_config.copy()

        if regime == 'trending':
            # 趋势市场：重视一致性和强度
            config['signal_scoring']['weights'] = {
                'accuracy': 0.25,
                'consistency': 0.50,
                'strength': 0.25
            }
        elif regime == 'volatile':
            # 高波动：重视强度和快速适应
            config['signal_scoring']['weights'] = {
                'accuracy': 0.20,
                'consistency': 0.30,
                'strength': 0.50
            }
            config['signal_scoring']['decay_lambda'] = 0.9  # 更快适应
        elif regime == 'ranging':
            # 震荡市场：重视准确率
            config['signal_scoring']['weights'] = {
                'accuracy': 0.50,
                'consistency': 0.30,
                'strength': 0.20
            }

        self.current_config = config
        self._save_config(config)
        print(f"  -> Adapted config for {regime} regime")

    def record_strategy_signal(self, strategy_name: str,
                               direction: float, strength: float,
                               price: float):
        """记录策略信号"""
        if strategy_name not in self.strategy_performances:
            self.strategy_performances[strategy_name] = StrategyPerformance(
                strategy_name=strategy_name
            )

        perf = self.strategy_performances[strategy_name]
        perf.signal_count += 1
        perf.last_updated = time.time()

        # 存储信号用于后续验证
        # (实际实现需要验证信号准确性)

    def record_weights(self, weights: Dict[str, float]):
        """记录权重快照"""
        self.weight_history.append({
            'timestamp': time.time(),
            'weights': weights.copy()
        })

        self.metrics['total_updates'] += 1

    def calculate_realtime_metrics(self) -> Dict:
        """计算实时指标"""
        if len(self.weight_history) < 10:
            return {'error': 'Insufficient data'}

        # 计算集中度
        latest = self.weight_history[-1]['weights']
        hhi = sum(w ** 2 for w in latest.values())

        # 计算有效策略数
        effective_n = 1 / hhi if hhi > 0 else 0

        # 计算权重波动率
        if len(self.weight_history) >= 20:
            recent_weights = []
            for wh in list(self.weight_history)[-20:]:
                recent_weights.extend(list(wh['weights'].values()))
            weight_volatility = np.std(recent_weights)
        else:
            weight_volatility = 0

        # 计算稳定性评分
        stability = 0
        if 0.15 <= hhi <= 0.25:
            stability += 40
        if effective_n >= 4:
            stability += 30
        if weight_volatility < 0.1:
            stability += 30

        return {
            'hhi': hhi,
            'effective_n': effective_n,
            'weight_volatility': weight_volatility,
            'stability_score': stability,
            'current_regime': self.regime_history[-1].regime if self.regime_history else 'unknown',
            'regime_confidence': self.regime_history[-1].confidence if self.regime_history else 0,
            'total_updates': self.metrics['total_updates'],
            'regime_transitions': self.metrics['regime_transitions']
        }

    async def optimization_loop(self):
        """优化循环"""
        while self.optimization_active:
            await asyncio.sleep(self.optimization_interval)

            metrics = self.calculate_realtime_metrics()
            if 'error' in metrics:
                continue

            print(f"\n[{datetime.now()}] Optimization check:")
            print(f"  Stability: {metrics['stability_score']}/100")
            print(f"  Regime: {metrics['current_regime']} "
                  f"({metrics['regime_confidence']:.2f})")

            # 如果稳定性低，尝试优化
            if metrics['stability_score'] < 60:
                print("  -> Low stability, triggering optimization...")
                await self._optimize_parameters()

            self.metrics['optimization_count'] += 1

    async def _optimize_parameters(self):
        """优化参数"""
        # 简化的随机搜索
        current = self.current_config['signal_scoring']['weights']

        # 生成小幅扰动
        noise = np.random.normal(0, 0.05, 3)
        new_weights = {
            'accuracy': max(0.1, min(0.6, current['accuracy'] + noise[0])),
            'consistency': max(0.1, min(0.6, current['consistency'] + noise[1])),
            'strength': max(0.1, min(0.6, current['strength'] + noise[2]))
        }

        # 归一化
        total = sum(new_weights.values())
        new_weights = {k: v / total for k, v in new_weights.items()}

        self.current_config['signal_scoring']['weights'] = new_weights
        self._save_config(self.current_config)

        print(f"  -> New weights: {new_weights}")

    def print_status(self):
        """打印当前状态"""
        metrics = self.calculate_realtime_metrics()

        print("\n" + "=" * 70)
        print(f"Live AutoResearch Status - {datetime.now()}")
        print("=" * 70)

        if 'error' in metrics:
            print(f"Status: {metrics['error']}")
        else:
            print(f"Stability Score: {metrics['stability_score']}/100")
            print(f"Market Regime: {metrics['current_regime'].upper()} "
                  f"({metrics['regime_confidence']:.1%} confidence)")
            print(f"HHI: {metrics['hhi']:.4f}")
            print(f"Effective N: {metrics['effective_n']:.2f}")
            print(f"Total Updates: {metrics['total_updates']}")
            print(f"Regime Transitions: {metrics['regime_transitions']}")
            print(f"Optimizations: {self.metrics['optimization_count']}")

        print("=" * 70)

    async def run(self):
        """主运行循环"""
        print("=" * 70)
        print("Live AutoResearch Trading System")
        print("=" * 70)
        print(f"Optimization interval: {self.optimization_interval}s")
        print("Press Ctrl+C to stop\n")

        self.optimization_active = True

        # 启动优化循环
        optimize_task = asyncio.create_task(self.optimization_loop())

        try:
            while self.optimization_active:
                self.print_status()
                await asyncio.sleep(60)  # 每分钟打印状态
        except KeyboardInterrupt:
            print("\n\nStopping...")
            self.optimization_active = False
            optimize_task.cancel()


# 集成到现有交易系统的接口
class LiveResearchIntegration:
    """与 SelfEvolvingTrader 的集成接口"""

    def __init__(self, trader):
        self.trader = trader
        self.live_research = LiveAutoResearch()
        self._running = False

    async def start(self):
        """启动实时研究"""
        self._running = True

        # 启动实时研究
        research_task = asyncio.create_task(self.live_research.run())

        # 定期同步数据
        while self._running:
            # 从trader获取数据
            if hasattr(self.trader, 'price_history') and self.trader.price_history:
                latest_price = self.trader.price_history[-1]
                self.live_research.update_price(latest_price)

            # 获取当前权重
            if hasattr(self.trader, 'meta_agent'):
                weights = self.trader.meta_agent.get_strategy_weights()
                self.live_research.record_weights(weights)

            await asyncio.sleep(5)

        research_task.cancel()

    def stop(self):
        """停止"""
        self._running = False


async def main():
    """测试运行"""
    research = LiveAutoResearch()

    # 模拟一些数据
    for i in range(100):
        price = 50000 + np.random.randn() * 100
        research.update_price(price)

        # 模拟权重
        weights = {
            'dual_ma': 0.2 + np.random.randn() * 0.05,
            'momentum': 0.2 + np.random.randn() * 0.05,
            'rsi': 0.2 + np.random.randn() * 0.05,
            'bollinger_bands': 0.2 + np.random.randn() * 0.05,
            'volatility_breakout': 0.2 + np.random.randn() * 0.05,
            'ml_momentum': 0.2 + np.random.randn() * 0.05
        }
        total = sum(weights.values())
        weights = {k: max(0.05, v / total) for k, v in weights.items()}
        research.record_weights(weights)

        time.sleep(0.01)

    await research.run()


if __name__ == '__main__':
    asyncio.run(main())
