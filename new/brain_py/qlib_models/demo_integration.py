"""
demo_integration.py - End-to-end smoke test for Qlib models in MetaAgent.

Demonstrates:
1. Instantiate LightGBM, LSTM, GRU QlibExpert agents
2. Register them via ExpertAdapter to MetaAgent
3. Run 100 synthetic trading cycles
4. Print regime distribution, strategy selection stats, average execution time
"""

import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from meta_agent import MetaAgent, MetaAgentConfig, ExpertAdapter
from agent_registry import AgentRegistry
from regime_detector import MarketRegimeDetector
from agents import MarketRegime
from qlib_models.adapters import QlibExpert, QlibExpertConfig
from qlib_models.gbdt.lightgbm_model import LightGBMModel
from qlib_models.neural.lstm_model import LSTMModel
from qlib_models.neural.gru_model import GRUModel


def generate_tabular_data(n_samples=300):
    np.random.seed(42)
    x = np.random.randn(n_samples, 400).astype(np.float32) * 0.1
    y = np.random.randn(n_samples).astype(np.float32) * 0.01
    return x, y


def generate_seq_data(n_samples=120):
    np.random.seed(43)
    x = np.random.randn(n_samples, 20, 20).astype(np.float32) * 0.1
    y = np.random.randn(n_samples).astype(np.float32) * 0.01
    return x, y


def main():
    print("[Demo] Training Qlib models...")
    tab_x, tab_y = generate_tabular_data(300)
    seq_x, seq_y = generate_seq_data(120)

    lgb_model = LightGBMModel()
    lgb_model.fit(tab_x, tab_y)
    print(f"  LightGBM fitted, loss={lgb_model.fit(tab_x, tab_y)['loss']:.6f}")

    lstm_model = LSTMModel()
    lstm_model.fit(seq_x, seq_y)
    print(f"  LSTM fitted, loss={lstm_model.fit(seq_x, seq_y)['loss']:.6f}")

    gru_model = GRUModel()
    gru_model.fit(seq_x, seq_y)
    print(f"  GRU fitted, loss={gru_model.fit(seq_x, seq_y)['loss']:.6f}")

    experts = [
        QlibExpert(QlibExpertConfig(name="qlib_lightgbm", model=lgb_model, suitable_regimes=[MarketRegime.TREND_UP, MarketRegime.TREND_DOWN])),
        QlibExpert(QlibExpertConfig(name="qlib_lstm", model=lstm_model, suitable_regimes=[MarketRegime.TREND_UP, MarketRegime.RANGE])),
        QlibExpert(QlibExpertConfig(name="qlib_gru", model=gru_model, suitable_regimes=[MarketRegime.HIGH_VOL, MarketRegime.TREND_DOWN])),
    ]

    registry = AgentRegistry()
    regime_detector = MarketRegimeDetector()
    meta_agent = MetaAgent(registry, regime_detector, MetaAgentConfig(strategy_switch_cooldown=0.1))

    for expert in experts:
        adapter = ExpertAdapter(expert)
        ok = meta_agent.register_strategy(adapter)
        print(f"[MetaAgent] Registered {expert.name}: {ok}")

    prices = np.cumsum(np.random.randn(300) * 0.01) + 100
    regime_detector.fit(prices)

    print("\n[Demo] Running 100 synthetic trading cycles...")
    selected_counts = {}
    for i in range(100):
        price = 100 + np.sin(i * 0.1) * 2 + np.random.randn() * 0.5
        observation = np.array([
            price * 0.999,
            price * 1.001,
            price,
            np.random.randn() * 0.5,
            np.random.randn() * 0.3,
            np.random.uniform(0, 1),
            np.random.uniform(0, 1),
            0.002,
            0.02 + np.random.rand() * 0.01,
        ], dtype=np.float32)

        result = meta_agent.execute(observation)
        name = result.selected_strategy or "none"
        selected_counts[name] = selected_counts.get(name, 0) + 1

    print("\n[Results]")
    print(f"  Regime distribution: {meta_agent.get_regime_distribution()}")
    print(f"  Strategy selections: {selected_counts}")
    print(f"  Avg execution time: {meta_agent.get_avg_execution_time():.2f} ms")

    stats = meta_agent.get_strategy_stats()
    for name, s in stats.items():
        print(f"  {name}: calls={s['total_calls']}, type={s['type']}, active={s['is_active']}")

    meta_agent.shutdown()
    print("\n[Demo] Complete.")


if __name__ == "__main__":
    main()
