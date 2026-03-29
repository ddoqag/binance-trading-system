#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple AI Trading System Demo (English)
No encoding issues
"""

import sys
import pandas as pd
import numpy as np
import logging
from pathlib import Path

# Set logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SimpleDemo')


def main():
    print("="*60)
    print("AI Trading System Demo")
    print("="*60)

    try:
        from ai_trading.market_analyzer import MarketAnalyzer, TrendType, MarketRegime
        from ai_trading.strategy_matcher import StrategyMatcher
        from ai_trading.ai_trading_system import AITradingSystem

        print("\n--- Step 1: Market Analyzer ---")
        analyzer = MarketAnalyzer()

        # Generate simulated data
        np.random.seed(42)
        dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
        base_price = 45000
        price_changes = np.random.normal(0, 0.005, 100)
        prices = base_price * (1 + price_changes).cumprod()
        volumes = np.random.randint(10000, 50000, 100)

        df = pd.DataFrame({
            'open': prices * (1 - np.random.normal(0, 0.001, 100)),
            'high': prices * (1 + np.random.normal(0, 0.002, 100)),
            'low': prices * (1 - np.random.normal(0, 0.002, 100)),
            'close': prices,
            'volume': volumes
        }, index=dates)

        print(f"Generated: {len(df)} candles")
        print(f"Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        analysis = analyzer.analyze_trend(df)
        print(f"\nMarket Analysis:")
        print(f"  Trend: {analysis['trend'].value}")
        print(f"  Regime: {analysis['regime'].value}")
        print(f"  Confidence: {analysis['confidence']:.2f}")
        print(f"  Current price: ${analysis['current_price']:.2f}")
        print(f"  Volatility: {analysis['volatility']:.4f}")

        print("\n--- Step 2: Strategy Matcher ---")
        matcher = StrategyMatcher()
        all_strategies = matcher.get_all_strategies()
        print(f"Registered strategies: {len(all_strategies)}")
        for name, config in all_strategies.items():
            print(f"  - {name}: {config.description[:40]}...")

        test_cases = [
            ("Uptrend", TrendType.UPTREND, MarketRegime.BULL, 0.85),
            ("Downtrend", TrendType.DOWNTREND, MarketRegime.BEAR, 0.75),
            ("Sideways", TrendType.SIDEWAYS, MarketRegime.NEUTRAL, 0.65),
        ]

        print(f"\nAuto strategy selection test:")
        for name, trend, regime, confidence in test_cases:
            trend_analysis = {
                'trend': trend,
                'regime': regime,
                'confidence': confidence
            }
            best = matcher.select_best_strategy(trend_analysis)
            print(f"  {name} -> {best.name}")

        print("\n--- Step 3: AI Trading System ---")
        config = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'initial_capital': 10000,
            'paper_trading': True,
            'model_path': None
        }

        system = AITradingSystem(config)
        print("System initialized")

        np.random.seed(123)
        dates = pd.date_range(start='2024-01-01', periods=300, freq='1h')
        base_price = 45000
        trend = np.linspace(0, 0.1, 300)
        noise = np.random.normal(0, 0.005, 300)
        prices = base_price * (1 + trend + noise).cumprod()
        volumes = np.random.randint(10000, 50000, 300)

        df = pd.DataFrame({
            'open': prices * (1 - np.random.normal(0, 0.001, 300)),
            'high': prices * (1 + np.random.normal(0, 0.002, 300)),
            'low': prices * (1 - np.random.normal(0, 0.002, 300)),
            'close': prices,
            'volume': volumes
        }, index=dates)

        print(f"Generated: {len(df)} candles")
        print(f"Price change: {(df['close'].iloc[-1]/df['close'].iloc[0]-1)*100:.2f}%")

        trend_analysis = system.analyze_market(df)
        print(f"\nMarket analysis:")
        print(f"  Trend: {trend_analysis['trend'].value}")
        print(f"  Regime: {trend_analysis['regime'].value}")
        print(f"  Confidence: {trend_analysis['confidence']:.2f}")

        strategy = system.select_and_apply_strategy(trend_analysis)
        print(f"\nAuto selected strategy: {strategy.name}")

        df_signals = system.generate_signals(df)
        signal_counts = df_signals['signal'].value_counts()
        print(f"\nSignal counts:")
        for s, c in signal_counts.items():
            print(f"  Signal {s}: {c} times")

        results = system.run_backtest(df, initial_capital=10000)
        print(f"\nBacktest results:")
        print(f"  Initial: ${results['initial_capital']:.2f}")
        print(f"  Final: ${results['final_value']:.2f}")
        print(f"  Return: {results['total_return']*100:.2f}%")
        print(f"  Trades: {results['total_trades']}")

        print("\n" + "="*60)
        print("SUCCESS!")
        print("="*60)
        print("\nKey points:")
        print("- System auto-selects best strategy based on market conditions")
        print("- No manual strategy selection needed")
        print("- Rule-based version works without AI model")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
