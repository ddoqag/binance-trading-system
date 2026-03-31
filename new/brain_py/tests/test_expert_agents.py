"""
test_expert_agents.py - Unit tests for expert agents

Tests cover:
- BaseExpert abstract class and shared functionality
- TrendFollowingExpert: trend detection and action generation
- MeanReversionExpert: mean reversion signals and confidence
- VolatilityExpert: volatility regime classification
- ExpertPool: expert registration and consensus

Coverage target: > 80%
"""

import pytest
import numpy as np
from dataclasses import dataclass

from brain_py.agents import (
    BaseExpert,
    ExpertConfig,
    ExpertPool,
    Action,
    ActionType,
    MarketRegime,
    TrendFollowingExpert,
    TrendFollowingConfig,
    MeanReversionExpert,
    MeanReversionConfig,
    VolatilityExpert,
    VolatilityConfig,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_observation():
    """Create a sample observation vector."""
    return np.array([
        50000.0,   # best_bid
        50001.0,   # best_ask
        50000.5,   # micro_price
        0.5,       # ofi_signal (positive = buying pressure)
        0.3,       # trade_imbalance
        0.3,       # bid_queue_pos
        0.7,       # ask_queue_pos
        0.00002,   # spread (0.002%)
        0.01,      # volatility
    ], dtype=np.float32)


@pytest.fixture
def downtrend_observation():
    """Create an observation indicating downtrend."""
    return np.array([
        49000.0,   # best_bid
        49001.0,   # best_ask
        49000.5,   # micro_price
        -0.6,      # ofi_signal (negative = selling pressure)
        -0.4,      # trade_imbalance
        0.7,       # bid_queue_pos
        0.3,       # ask_queue_pos
        0.00002,   # spread
        0.015,     # volatility
    ], dtype=np.float32)


@pytest.fixture
def range_bound_observation():
    """Create an observation for range-bound market."""
    return np.array([
        50000.0,   # best_bid
        50000.5,   # best_ask (tight spread)
        50000.8,   # micro_price (above mid = overbought)
        0.1,       # weak ofi
        0.05,      # weak trade imbalance
        0.5,       # balanced queue
        0.5,       # balanced queue
        0.00001,   # very tight spread
        0.005,     # low volatility
    ], dtype=np.float32)


@pytest.fixture
def high_vol_observation():
    """Create an observation for high volatility."""
    return np.array([
        50000.0,   # best_bid
        50005.0,   # best_ask (wide spread)
        50002.0,   # micro_price
        0.8,       # strong ofi
        0.5,       # strong trade imbalance
        0.2,       # bid_queue_pos
        0.8,       # ask_queue_pos
        0.0001,    # wide spread
        0.05,      # high volatility
    ], dtype=np.float32)


@pytest.fixture
def trend_expert():
    """Create a trend following expert."""
    cfg = TrendFollowingConfig(name="trend_following")
    return TrendFollowingExpert(cfg)


@pytest.fixture
def reversion_expert():
    """Create a mean reversion expert."""
    cfg = MeanReversionConfig(name="mean_reversion")
    return MeanReversionExpert(cfg)


@pytest.fixture
def volatility_expert():
    """Create a volatility expert."""
    cfg = VolatilityConfig(name="volatility")
    return VolatilityExpert(cfg)


@pytest.fixture
def expert_pool():
    """Create an expert pool with all experts registered."""
    pool = ExpertPool()
    # Use unique names to avoid conflicts
    trend_cfg = TrendFollowingConfig(name="trend_following")
    reversion_cfg = MeanReversionConfig(name="mean_reversion")
    vol_cfg = VolatilityConfig(name="volatility")
    pool.register_expert(TrendFollowingExpert(trend_cfg))
    pool.register_expert(MeanReversionExpert(reversion_cfg))
    pool.register_expert(VolatilityExpert(vol_cfg))
    return pool


# =============================================================================
# BaseExpert Tests
# =============================================================================

class TestBaseExpert:
    """Tests for BaseExpert base class functionality."""

    def test_expert_config_defaults(self):
        """Test default ExpertConfig values."""
        config = ExpertConfig()
        assert config.name == "base_expert"
        assert config.min_confidence == 0.3
        assert config.max_position_size == 1.0
        assert config.lookback_window == 20
        assert config.feature_dim == 9

    def test_action_creation(self):
        """Test Action dataclass creation."""
        action = Action(
            action_type=ActionType.BUY,
            position_size=0.5,
            confidence=0.8,
            metadata={'test': 'data'}
        )
        assert action.action_type == ActionType.BUY
        assert action.position_size == 0.5
        assert action.confidence == 0.8
        assert action.metadata == {'test': 'data'}

    def test_action_default_metadata(self):
        """Test Action with default metadata."""
        action = Action(
            action_type=ActionType.HOLD,
            position_size=0.0,
            confidence=0.5
        )
        assert action.metadata == {}

    def test_market_regime_enum(self):
        """Test MarketRegime enum values."""
        assert MarketRegime.UNKNOWN == 0
        assert MarketRegime.TREND_UP == 1
        assert MarketRegime.TREND_DOWN == 2
        assert MarketRegime.RANGE == 3
        assert MarketRegime.HIGH_VOL == 4
        assert MarketRegime.LOW_VOL == 5

    def test_action_type_enum(self):
        """Test ActionType enum values."""
        assert ActionType.HOLD == 0
        assert ActionType.BUY == 1
        assert ActionType.SELL == 2


# =============================================================================
# TrendFollowingExpert Tests
# =============================================================================

class TestTrendFollowingExpert:
    """Tests for TrendFollowingExpert."""

    def test_initialization(self, trend_expert):
        """Test expert initialization."""
        assert trend_expert.name == "trend_following"
        # Config values come from TrendFollowingConfig defaults
        assert trend_expert.config.min_confidence == 0.3
        assert trend_expert.config.max_position_size == 1.0

    def test_get_expertise(self, trend_expert):
        """Test expert reports correct regimes."""
        expertise = trend_expert.get_expertise()
        assert MarketRegime.TREND_UP in expertise
        assert MarketRegime.TREND_DOWN in expertise
        assert MarketRegime.RANGE not in expertise

    def test_is_expert_in(self, trend_expert):
        """Test is_expert_in method."""
        assert trend_expert.is_expert_in(MarketRegime.TREND_UP) is True
        assert trend_expert.is_expert_in(MarketRegime.TREND_DOWN) is True
        assert trend_expert.is_expert_in(MarketRegime.RANGE) is False
        assert trend_expert.is_expert_in(MarketRegime.HIGH_VOL) is False

    def test_buy_signal_uptrend(self, trend_expert, sample_observation):
        """Test buy signal in uptrend."""
        action = trend_expert.act(sample_observation)
        assert action.action_type == ActionType.BUY
        assert action.position_size > 0
        assert action.confidence > 0
        assert action.metadata['expert_type'] == 'trend_following'
        assert 'trend_strength' in action.metadata

    def test_sell_signal_downtrend(self, trend_expert, downtrend_observation):
        """Test sell signal in downtrend."""
        action = trend_expert.act(downtrend_observation)
        assert action.action_type == ActionType.SELL
        assert action.position_size < 0
        assert action.confidence > 0

    def test_hold_signal_weak_trend(self, trend_expert):
        """Test hold signal when trend is weak."""
        weak_obs = np.array([
            50000.0, 50001.0, 50000.5,
            0.05, 0.05,  # weak signals
            0.5, 0.5, 0.00002, 0.01
        ], dtype=np.float32)
        action = trend_expert.act(weak_obs)
        assert action.action_type == ActionType.HOLD
        assert abs(action.position_size) < 0.1

    def test_confidence_calculation(self, trend_expert, sample_observation):
        """Test confidence calculation."""
        confidence = trend_expert.get_confidence(sample_observation)
        assert 0.0 <= confidence <= 1.0

    def test_confidence_with_agreement(self, trend_expert, sample_observation):
        """Test higher confidence when signals agree."""
        # OFI and trade imbalance both positive
        conf1 = trend_expert.get_confidence(sample_observation)

        # OFI positive, trade imbalance negative (disagreement)
        obs_disagree = sample_observation.copy()
        obs_disagree[4] = -0.3
        conf2 = trend_expert.get_confidence(obs_disagree)

        assert conf1 > conf2

    def test_position_size_limits(self, trend_expert, sample_observation):
        """Test position size respects limits."""
        action = trend_expert.act(sample_observation)
        assert abs(action.position_size) <= trend_expert.config.max_position_size

    def test_should_enter_long(self, trend_expert, sample_observation, downtrend_observation):
        """Test long entry condition."""
        assert bool(trend_expert.should_enter_long(sample_observation)) is True
        assert bool(trend_expert.should_enter_long(downtrend_observation)) is False

    def test_should_enter_short(self, trend_expert, sample_observation, downtrend_observation):
        """Test short entry condition."""
        assert bool(trend_expert.should_enter_short(downtrend_observation)) is True
        assert bool(trend_expert.should_enter_short(sample_observation)) is False

    def test_observation_validation(self, trend_expert):
        """Test observation validation handles NaN/Inf."""
        obs_with_nan = np.array([np.nan, 1.0, 2.0, 0.5, 0.3, 0.5, 0.5, 0.0001, 0.01])
        action = trend_expert.act(obs_with_nan)
        assert isinstance(action, Action)
        assert action.action_type in [ActionType.BUY, ActionType.SELL, ActionType.HOLD]

    def test_performance_tracking(self, trend_expert):
        """Test performance statistics tracking."""
        trend_expert.update_performance(0.5, 0.3)
        assert trend_expert._performance_stats['calls'] == 1
        assert trend_expert._performance_stats['total_pnl'] == 0.3

        trend_expert.update_performance(-0.2, -0.1)
        assert trend_expert._performance_stats['calls'] == 2
        assert trend_expert._performance_stats['correct_predictions'] == 2

    def test_get_accuracy(self, trend_expert):
        """Test accuracy calculation."""
        assert trend_expert.get_accuracy() == 0.5  # Default when no calls

        trend_expert.update_performance(0.5, 0.3)  # Correct
        trend_expert.update_performance(-0.2, 0.1)  # Incorrect
        accuracy = trend_expert.get_accuracy()
        assert accuracy == 0.5

    def test_get_average_pnl(self, trend_expert):
        """Test average PnL calculation."""
        assert trend_expert.get_average_pnl() == 0.0

        trend_expert.update_performance(0.5, 0.3)
        trend_expert.update_performance(0.2, 0.2)
        assert trend_expert.get_average_pnl() == 0.25

    def test_reset_stats(self, trend_expert):
        """Test statistics reset."""
        trend_expert.update_performance(0.5, 0.3)
        trend_expert.reset_stats()
        assert trend_expert._performance_stats['calls'] == 0
        assert trend_expert._performance_stats['total_pnl'] == 0.0


# =============================================================================
# MeanReversionExpert Tests
# =============================================================================

class TestMeanReversionExpert:
    """Tests for MeanReversionExpert."""

    def test_initialization(self, reversion_expert):
        """Test expert initialization."""
        assert reversion_expert.name == "mean_reversion"
        # Config values come from MeanReversionConfig defaults
        assert reversion_expert.config.min_confidence == 0.3
        assert reversion_expert.config.max_position_size == 1.0

    def test_get_expertise(self, reversion_expert):
        """Test expert reports correct regimes."""
        expertise = reversion_expert.get_expertise()
        assert MarketRegime.RANGE in expertise
        assert MarketRegime.TREND_UP not in expertise

    def test_deviation_calculation(self, reversion_expert):
        """Test price deviation calculation."""
        micro = 50100.0
        mid = 50000.0
        deviation = reversion_expert._calculate_deviation(micro, mid)
        expected = (50100.0 - 50000.0) / 50000.0
        assert abs(deviation - expected) < 1e-6

    def test_deviation_zero_mid(self, reversion_expert):
        """Test deviation with zero mid price."""
        deviation = reversion_expert._calculate_deviation(100.0, 0.0)
        assert deviation == 0.0

    def test_buy_signal_overbought(self, reversion_expert):
        """Test buy signal when price below mid (oversold)."""
        obs = np.array([
            50000.0, 50001.0, 49999.0,  # micro_price below mid
            0.1, 0.05, 0.6, 0.4, 0.0001, 0.005
        ], dtype=np.float32)
        action = reversion_expert.act(obs)
        # Price is below mid, should buy (expect reversion up)
        assert action.action_type in [ActionType.BUY, ActionType.HOLD]

    def test_sell_signal_oversold(self, reversion_expert):
        """Test sell signal when price above mid (overbought)."""
        obs = np.array([
            50000.0, 50001.0, 50002.0,  # micro_price above mid
            0.1, 0.05, 0.4, 0.6, 0.0001, 0.005
        ], dtype=np.float32)
        action = reversion_expert.act(obs)
        # Price is above mid, should sell (expect reversion down)
        assert action.action_type in [ActionType.SELL, ActionType.HOLD]

    def test_hold_on_small_spread(self, reversion_expert):
        """Test hold when spread is too small."""
        obs = np.array([
            50000.0, 50000.001, 50000.0005,  # very small spread
            0.1, 0.05, 0.5, 0.5, 0.0000001, 0.005
        ], dtype=np.float32)
        action = reversion_expert.act(obs)
        assert action.action_type == ActionType.HOLD

    def test_confidence_bounds(self, reversion_expert, range_bound_observation):
        """Test confidence is within bounds."""
        confidence = reversion_expert.get_confidence(range_bound_observation)
        assert 0.0 <= confidence <= 1.0

    def test_historical_mean_reversion_check(self, reversion_expert):
        """Test historical mean reversion check."""
        # Fill with mean-reverting data (sine wave)
        t = np.linspace(0, 4*np.pi, 50)
        reversion_expert._price_history = list(50000 + 100 * np.sin(t))
        score = reversion_expert._check_historical_mean_reversion()
        assert 0.0 <= score <= 1.0

    def test_historical_check_insufficient_data(self, reversion_expert):
        """Test historical check with insufficient data."""
        reversion_expert._price_history = [50000.0, 50001.0]
        score = reversion_expert._check_historical_mean_reversion()
        assert score == 0.5  # Default value

    def test_reset_history(self, reversion_expert):
        """Test history reset."""
        reversion_expert._price_history = [50000.0, 50001.0]
        reversion_expert.reset_history()
        assert len(reversion_expert._price_history) == 0

    def test_price_history_accumulation(self, reversion_expert):
        """Test price history accumulation and limit."""
        obs = np.array([
            50000.0, 50001.0, 50000.5,
            0.1, 0.05, 0.5, 0.5, 0.0001, 0.005
        ], dtype=np.float32)

        for _ in range(110):
            reversion_expert.act(obs)

        assert len(reversion_expert._price_history) <= reversion_expert._max_history


# =============================================================================
# VolatilityExpert Tests
# =============================================================================

class TestVolatilityExpert:
    """Tests for VolatilityExpert."""

    def test_initialization(self, volatility_expert):
        """Test expert initialization."""
        assert volatility_expert.name == "volatility"
        # Config values come from VolatilityConfig defaults
        assert volatility_expert.config.min_confidence == 0.3
        assert volatility_expert.config.max_position_size == 1.0

    def test_get_expertise(self, volatility_expert):
        """Test expert reports correct regimes."""
        expertise = volatility_expert.get_expertise()
        assert MarketRegime.HIGH_VOL in expertise
        assert MarketRegime.LOW_VOL in expertise
        assert MarketRegime.TREND_UP not in expertise

    def test_volatility_classification_high(self, volatility_expert):
        """Test high volatility classification."""
        vol = volatility_expert.config.high_vol_threshold + 0.01
        regime = volatility_expert._classify_volatility(vol)
        assert regime == "high"

    def test_volatility_classification_low(self, volatility_expert):
        """Test low volatility classification."""
        vol = volatility_expert.config.low_vol_threshold - 0.001
        regime = volatility_expert._classify_volatility(vol)
        assert regime == "low"

    def test_volatility_classification_medium(self, volatility_expert):
        """Test medium volatility classification."""
        vol = (volatility_expert.config.low_vol_threshold +
               volatility_expert.config.high_vol_threshold) / 2
        regime = volatility_expert._classify_volatility(vol)
        assert regime == "medium"

    def test_estimate_volatility_insufficient_data(self, volatility_expert):
        """Test volatility estimation with no data."""
        vol = volatility_expert._estimate_volatility()
        assert vol == 0.01  # Default value

    def test_estimate_volatility_with_data(self, volatility_expert):
        """Test volatility estimation with price history."""
        # Add price history with known volatility
        prices = np.cumsum(np.random.randn(30) * 0.001) + 50000
        volatility_expert._price_history = list(prices)
        vol = volatility_expert._estimate_volatility()
        assert vol > 0

    def test_action_in_high_vol(self, volatility_expert, high_vol_observation):
        """Test action in high volatility regime."""
        action = volatility_expert.act(high_vol_observation)
        assert isinstance(action, Action)
        assert action.action_type in [ActionType.BUY, ActionType.SELL, ActionType.HOLD]
        assert 'vol_regime' in action.metadata
        assert action.metadata['vol_regime'] == 'high'

    def test_action_in_low_vol(self, volatility_expert):
        """Test action in low volatility regime."""
        obs = np.array([
            50000.0, 50000.5, 50000.25,
            0.2, 0.1, 0.5, 0.5, 0.00001, 0.002  # low vol
        ], dtype=np.float32)
        action = volatility_expert.act(obs)
        assert isinstance(action, Action)
        assert action.metadata['vol_regime'] == 'low'

    def test_position_scaling_high_vol(self, volatility_expert, high_vol_observation):
        """Test position size is scaled down in high volatility."""
        action = volatility_expert.act(high_vol_observation)
        if action.action_type != ActionType.HOLD:
            # In high vol, position should be scaled by position_scale_factor
            max_expected = volatility_expert.config.max_position_size * \
                          volatility_expert.config.position_scale_factor
            assert abs(action.position_size) <= max_expected * 1.5  # Allow some margin

    def test_confidence_high_vol(self, volatility_expert, high_vol_observation):
        """Test confidence calculation in high volatility."""
        confidence = volatility_expert.get_confidence(high_vol_observation)
        assert 0.0 <= confidence <= 1.0

    def test_volatility_stability_calculation(self, volatility_expert):
        """Test volatility stability calculation."""
        # With insufficient data
        stability = volatility_expert._calculate_vol_stability()
        assert stability == 0.5

        # With sufficient data
        volatility_expert._volatility_history = [0.01] * 10
        stability = volatility_expert._calculate_vol_stability()
        assert 0.0 <= stability <= 1.0

    def test_volatility_forecast(self, volatility_expert):
        """Test volatility forecast."""
        # With insufficient data
        forecast = volatility_expert.get_volatility_forecast()
        assert forecast == 0.01  # Default from _estimate_volatility

        # With sufficient data
        volatility_expert._volatility_history = list(np.linspace(0.01, 0.02, 20))
        forecast = volatility_expert.get_volatility_forecast()
        assert forecast > 0

    def test_history_tracking(self, volatility_expert):
        """Test volatility and price history tracking."""
        obs = np.array([
            50000.0, 50001.0, 50000.5,
            0.5, 0.3, 0.3, 0.7, 0.00002, 0.01
        ], dtype=np.float32)

        for _ in range(10):
            volatility_expert.act(obs)

        assert len(volatility_expert._price_history) > 0
        assert len(volatility_expert._volatility_history) > 0

    def test_reset_history(self, volatility_expert):
        """Test history reset."""
        volatility_expert._price_history = [50000.0]
        volatility_expert._volatility_history = [0.01]
        volatility_expert.reset_history()
        assert len(volatility_expert._price_history) == 0
        assert len(volatility_expert._volatility_history) == 0


# =============================================================================
# ExpertPool Tests
# =============================================================================

class TestExpertPool:
    """Tests for ExpertPool."""

    def test_initialization(self):
        """Test pool initialization."""
        pool = ExpertPool()
        assert len(pool.get_all_experts()) == 0

    def test_register_expert(self, expert_pool):
        """Test expert registration."""
        assert len(expert_pool.get_all_experts()) == 3

    def test_register_updates_regime_map(self, expert_pool):
        """Test registration updates regime map."""
        trend_experts = expert_pool.get_experts_for_regime(MarketRegime.TREND_UP)
        assert len(trend_experts) == 1
        assert trend_experts[0].name == "trend_following"

    def test_get_experts_for_range_regime(self, expert_pool):
        """Test getting experts for range regime."""
        experts = expert_pool.get_experts_for_regime(MarketRegime.RANGE)
        assert len(experts) == 1
        assert experts[0].name == "mean_reversion"

    def test_get_experts_for_vol_regimes(self, expert_pool):
        """Test getting experts for volatility regimes."""
        high_vol_experts = expert_pool.get_experts_for_regime(MarketRegime.HIGH_VOL)
        low_vol_experts = expert_pool.get_experts_for_regime(MarketRegime.LOW_VOL)
        assert len(high_vol_experts) == 1
        assert len(low_vol_experts) == 1
        assert high_vol_experts[0].name == "volatility"

    def test_get_experts_for_unknown_regime(self, expert_pool):
        """Test getting experts for unknown regime."""
        experts = expert_pool.get_experts_for_regime(MarketRegime.UNKNOWN)
        assert len(experts) == 0

    def test_unregister_expert(self, expert_pool):
        """Test expert unregistration."""
        expert_pool.unregister_expert("trend_following")
        assert len(expert_pool.get_all_experts()) == 2
        trend_experts = expert_pool.get_experts_for_regime(MarketRegime.TREND_UP)
        assert len(trend_experts) == 0

    def test_unregister_nonexistent(self, expert_pool):
        """Test unregistering non-existent expert."""
        expert_pool.unregister_expert("nonexistent")
        assert len(expert_pool.get_all_experts()) == 3

    def test_collect_actions(self, expert_pool, sample_observation):
        """Test collecting actions from experts."""
        actions = expert_pool.collect_actions(sample_observation, MarketRegime.TREND_UP)
        assert len(actions) == 1
        name, action = actions[0]
        assert name == "trend_following"
        assert isinstance(action, Action)

    def test_collect_actions_empty_regime(self, expert_pool, sample_observation):
        """Test collecting actions for regime with no experts."""
        actions = expert_pool.collect_actions(sample_observation, MarketRegime.UNKNOWN)
        assert len(actions) == 0

    def test_weighted_consensus(self, expert_pool, sample_observation):
        """Test weighted consensus calculation."""
        consensus = expert_pool.get_weighted_consensus(
            sample_observation, MarketRegime.TREND_UP
        )
        assert isinstance(consensus, Action)
        assert 0.0 <= consensus.confidence <= 1.0

    def test_weighted_consensus_empty(self, expert_pool, sample_observation):
        """Test weighted consensus with no experts."""
        consensus = expert_pool.get_weighted_consensus(
            sample_observation, MarketRegime.UNKNOWN
        )
        assert consensus.action_type == ActionType.HOLD
        assert consensus.position_size == 0.0
        assert consensus.confidence == 0.0

    def test_weighted_consensus_with_custom_weights(self, expert_pool, sample_observation):
        """Test weighted consensus with custom weights."""
        weights = {"trend_following": 2.0}
        consensus = expert_pool.get_weighted_consensus(
            sample_observation, MarketRegime.TREND_UP, weights
        )
        assert isinstance(consensus, Action)

    def test_multiple_experts_same_regime(self):
        """Test pool with multiple experts for same regime."""
        pool = ExpertPool()
        cfg1 = TrendFollowingConfig(name="trend_following_1")
        pool.register_expert(TrendFollowingExpert(cfg1))

        # Create another trend expert with different config
        cfg2 = TrendFollowingConfig(name="trend_following_2")
        expert2 = TrendFollowingExpert(cfg2)
        pool.register_expert(expert2)

        experts = pool.get_experts_for_regime(MarketRegime.TREND_UP)
        assert len(experts) == 2


# =============================================================================
# Integration Tests
# =============================================================================

class TestExpertIntegration:
    """Integration tests for expert agents."""

    def test_all_experts_return_valid_actions(self, expert_pool, sample_observation):
        """Test all experts return valid actions."""
        for expert in expert_pool.get_all_experts():
            action = expert.act(sample_observation)
            assert isinstance(action, Action)
            assert action.action_type in [ActionType.HOLD, ActionType.BUY, ActionType.SELL]
            assert -1.0 <= action.position_size <= 1.0
            assert 0.0 <= action.confidence <= 1.0

    def test_all_experts_return_confidence(self, expert_pool, sample_observation):
        """Test all experts return valid confidence."""
        for expert in expert_pool.get_all_experts():
            confidence = expert.get_confidence(sample_observation)
            assert isinstance(confidence, (float, np.floating))
            assert 0.0 <= float(confidence) <= 1.0

    def test_expert_predictions_differ_by_regime(self):
        """Test that different experts are active in different regimes."""
        pool = ExpertPool()
        trend_cfg = TrendFollowingConfig(name="trend_following")
        range_cfg = MeanReversionConfig(name="mean_reversion")
        pool.register_expert(TrendFollowingExpert(trend_cfg))
        pool.register_expert(MeanReversionExpert(range_cfg))

        trend_experts = pool.get_experts_for_regime(MarketRegime.TREND_UP)
        range_experts = pool.get_experts_for_regime(MarketRegime.RANGE)

        assert trend_experts != range_experts
        assert len(trend_experts) == 1
        assert len(range_experts) == 1

    def test_full_trading_cycle(self, expert_pool):
        """Test a full trading cycle with regime switching."""
        observations = [
            # Uptrend observation
            np.array([50000.0, 50001.0, 50000.5, 0.6, 0.4, 0.3, 0.7, 0.00002, 0.01]),
            # Range-bound observation
            np.array([50000.0, 50000.5, 50000.8, 0.1, 0.05, 0.5, 0.5, 0.00001, 0.005]),
            # High vol observation
            np.array([50000.0, 50005.0, 50002.0, 0.8, 0.5, 0.2, 0.8, 0.0001, 0.05]),
        ]

        regimes = [MarketRegime.TREND_UP, MarketRegime.RANGE, MarketRegime.HIGH_VOL]

        for obs, regime in zip(observations, regimes):
            actions = expert_pool.collect_actions(obs, regime)
            assert len(actions) > 0
            for name, action in actions:
                assert isinstance(action, Action)
                expert = next(e for e in expert_pool.get_all_experts() if e.name == name)
                assert expert.is_expert_in(regime)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
