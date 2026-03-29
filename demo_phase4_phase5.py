#!/usr/bin/env python3
"""
RL决策融合 + 高频执行 综合演示
展示Phase 4和Phase 5实现的集成使用
"""

import numpy as np
import pandas as pd
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('IntegratedDemo')


def demo_rl_meta_controller():
    """演示RL Meta-Controller"""
    logger.info("=" * 60)
    logger.info("RL Meta-Controller Demo")
    logger.info("=" * 60)

    try:
        from rl.meta_controller import create_meta_controller, MarketRegime

        # 创建Meta-Controller
        strategy_names = ["DualMA", "RSI", "ML_Predictor", "Breakout", "MeanReversion"]
        controller = create_meta_controller(strategy_names, hidden_dims=[128, 64])

        logger.info(f"Created Meta-Controller with {len(strategy_names)} strategies")
        logger.info(f"State dim: {controller.state_dim}, Action dim: {controller.action_dim}")

        # 模拟运行几步
        for step in range(5):
            # 模拟策略收益
            strategy_returns = {
                name: np.random.randn() * 0.02
                for name in strategy_names
            }

            # 模拟市场状态
            market_regime = MarketRegime(
                regime_type=np.random.choice(["bull", "bear", "neutral", "high_volatility"]),
                trend_strength=np.random.uniform(-0.5, 0.5),
                volatility_percentile=np.random.uniform(0, 1)
            )

            # 模拟组合价值
            portfolio_value = 1.0 + step * 0.01

            # 观察
            state = controller.observe(strategy_returns, market_regime, portfolio_value)

            # 选择动作
            action = controller.select_action(state, training=True)

            # 计算新权重
            new_weights = controller.compute_weights(action)

            # 更新权重
            controller.state_manager.update_weights(new_weights)

            logger.info(f"Step {step}: Market={market_regime.regime_type}, Weights={new_weights.round(3)}")

        # 获取当前权重
        current_weights = controller.get_current_weights()
        logger.info(f"Final weights: {current_weights}")

        return True

    except Exception as e:
        logger.error(f"Meta-Controller demo failed: {e}")
        return False


def demo_strategy_pool():
    """演示Strategy Pool"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Strategy Pool Demo")
    logger.info("=" * 60)

    try:
        from rl.strategy_pool import StrategyPool, StrategyConfig, StrategyType
        from strategy.dual_ma import DualMAStrategy
        from strategy.rsi_strategy import RSIStrategy

        # 创建策略池
        pool = StrategyPool()

        # 注册策略
        pool.register_strategy(StrategyConfig(
            name="DualMA",
            strategy_class=DualMAStrategy,
            params={"fast_period": 12, "slow_period": 26},
            strategy_type=StrategyType.TREND_FOLLOWING,
            default_weight=0.4
        ))

        pool.register_strategy(StrategyConfig(
            name="RSI",
            strategy_class=RSIStrategy,
            params={"period": 14, "oversold": 30, "overbought": 70},
            strategy_type=StrategyType.MEAN_REVERSION,
            default_weight=0.3
        ))

        # 模拟市场数据
        data = pd.DataFrame({
            'open': np.random.randn(100).cumsum() + 100,
            'high': np.random.randn(100).cumsum() + 101,
            'low': np.random.randn(100).cumsum() + 99,
            'close': np.random.randn(100).cumsum() + 100,
            'volume': np.random.randint(1000, 10000, 100)
        })

        # 生成信号
        signals = pool.generate_signals(data)
        logger.info(f"Generated signals from {len(signals)} strategies")

        # 计算共识
        consensus = pool.compute_consensus_signal(signals)
        logger.info(f"Consensus: {consensus['consensus']}, Confidence: {consensus['confidence']:.2f}")

        # 更新权重
        new_weights = {"DualMA": 0.6, "RSI": 0.4}
        pool.update_weights(new_weights)

        # 获取汇总
        summary = pool.get_pool_summary()
        logger.info(f"Pool summary: {summary}")

        return True

    except Exception as e:
        logger.error(f"Strategy Pool demo failed: {e}")
        return False


def demo_fusion_trainer():
    """演示Fusion Trainer"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Fusion Trainer Demo")
    logger.info("=" * 60)

    try:
        from rl.fusion_trainer import FusionTrainerDemo

        # 使用演示模式（不会运行完整训练，只展示结构）
        logger.info("Fusion Trainer structure:")
        logger.info("- Coordinates Meta-Controller and Strategy Pool")
        logger.info("- Trains strategy weight allocation")
        logger.info("- Optimizes for Sharpe ratio and drawdown")

        # 创建模拟数据
        market_data, strategy_signals = FusionTrainerDemo.create_mock_data(n_days=100)
        logger.info(f"Created mock data: {len(market_data)} days, {len(strategy_signals)} strategies")

        return True

    except Exception as e:
        logger.error(f"Fusion Trainer demo failed: {e}")
        return False


def demo_orderbook_strategies():
    """演示订单簿策略"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Order Book Strategies Demo")
    logger.info("=" * 60)

    try:
        from strategy.orderbook_strategies import (
            OrderBook, OrderBookLevel, OrderBookStrategyManager,
            ImbalanceStrategy, MomentumImbalanceStrategy
        )

        # 创建订单簿
        bids = [OrderBookLevel(price=50000 - i * 10, quantity=1.0 + i * 0.5) for i in range(10)]
        asks = [OrderBookLevel(price=50010 + i * 10, quantity=1.0 + i * 0.5) for i in range(10)]

        orderbook = OrderBook(
            symbol="BTCUSDT",
            bids=bids,
            asks=asks,
            timestamp=datetime.now()
        )

        logger.info(f"Orderbook mid: {orderbook.mid_price}, Spread: {orderbook.spread}")

        # 创建策略管理器
        manager = OrderBookStrategyManager()
        manager.register_strategy("imbalance", ImbalanceStrategy(), weight=1.0)
        manager.register_strategy("momentum", MomentumImbalanceStrategy(), weight=0.8)

        # 生成信号
        signal, strength, details = manager.generate_combined_signal(orderbook)

        logger.info(f"Signal: {signal.name}, Strength: {strength:.2f}")
        logger.info(f"Individual signals: {details['individual_signals']}")

        return True

    except Exception as e:
        logger.error(f"Order Book Strategies demo failed: {e}")
        return False


def demo_rust_execution():
    """演示Rust执行引擎"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("Rust Execution Engine Demo")
    logger.info("=" * 60)

    try:
        from trading.rust_execution_bridge import create_rust_engine, RustExecutionConfig

        # 创建引擎（如果没有编译Rust，会使用Python回退）
        config = RustExecutionConfig(
            worker_threads=4,
            slippage_model="fixed"
        )

        engine = create_rust_engine(config)
        logger.info(f"Engine created (Rust available: {engine.is_rust_available()})")

        # 模拟市场数据
        engine.simulate_market_data("BTCUSDT", 50000.0)

        # 提交订单
        order = {
            'symbol': 'BTCUSDT',
            'side': 'BUY',
            'order_type': 'MARKET',
            'quantity': 0.1,
        }

        result = engine.submit_order(order)
        logger.info(f"Order result: success={result['success']}, price={result['executed_price']:.2f}")

        # 获取统计
        stats = engine.get_stats()
        logger.info(f"Engine stats: {stats}")

        return True

    except Exception as e:
        logger.error(f"Rust Execution demo failed: {e}")
        return False


def main():
    """主函数"""
    logger.info("\n" + "=" * 60)
    logger.info("Phase 4 & 5 Integration Demo")
    logger.info("RL Decision Fusion + High-Frequency Execution")
    logger.info("=" * 60 + "\n")

    results = {}

    # Phase 4: RL Decision Fusion
    results['RL Meta-Controller'] = demo_rl_meta_controller()
    results['Strategy Pool'] = demo_strategy_pool()
    results['Fusion Trainer'] = demo_fusion_trainer()

    # Phase 5: High-Frequency Optimization
    results['Order Book Strategies'] = demo_orderbook_strategies()
    results['Rust Execution Engine'] = demo_rust_execution()

    # 总结
    logger.info("")
    logger.info("=" * 60)
    logger.info("Demo Summary")
    logger.info("=" * 60)

    for component, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"{component}: {status}")

    success_count = sum(results.values())
    total_count = len(results)

    logger.info("")
    logger.info(f"Total: {success_count}/{total_count} components working")

    if success_count == total_count:
        logger.info("\n🎉 All components ready for use!")
    else:
        logger.info("\n⚠️  Some components need attention (see logs above)")

    return results


if __name__ == "__main__":
    main()
