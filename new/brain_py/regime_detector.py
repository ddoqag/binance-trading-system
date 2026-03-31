"""
regime_detector.py - Market Regime Detection using HMM and GARCH.

Provides:
- Hidden Markov Model (HMM) for regime classification
- GARCH model for volatility forecasting
- Real-time regime detection with low latency

Regimes:
- TRENDING: Persistent directional price movement
- MEAN_REVERTING: Oscillating around mean price
- HIGH_VOLATILITY: Large price swings, high uncertainty
"""

import numpy as np
from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict
from collections import deque
import time
import warnings

# Suppress sklearn warnings
warnings.filterwarnings('ignore', category=FutureWarning)

# Optional imports - will use fallback if not available
try:
    from hmmlearn.hmm import GaussianHMM
    HMMLEARN_AVAILABLE = True
except ImportError:
    HMMLEARN_AVAILABLE = False
    GaussianHMM = None

try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False
    arch_model = None

try:
    from .features.regime_features import RegimeFeatureExtractor, RegimeFeatures
except ImportError:
    from features.regime_features import RegimeFeatureExtractor, RegimeFeatures


class Regime(Enum):
    """Market regime types."""
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"


@dataclass
class RegimePrediction:
    """Output of regime detection."""
    regime: Regime
    confidence: float  # 0.0 - 1.0
    probabilities: Dict[Regime, float]
    volatility_forecast: float
    timestamp: float


class MarketRegimeDetector:
    """
    Market regime detector using HMM and GARCH models.

    Combines:
    1. Gaussian HMM for regime classification based on return features
    2. GARCH(1,1) for volatility forecasting
    3. Feature extraction for state representation

    Performance targets:
    - Detection latency: < 1 second
    - Prediction accuracy: > 60%
    """

    def __init__(self, n_states: int = 3, feature_window: int = 100):
        """
        Initialize regime detector.

        Args:
            n_states: Number of HMM hidden states (default 3 for 3 regimes)
            feature_window: Window size for feature extraction
        """
        self.n_states = n_states
        self.feature_window = feature_window

        # Feature extractor
        self.feature_extractor = RegimeFeatureExtractor(
            window=feature_window,
            min_samples=30
        )

        # HMM model
        self.hmm: Optional[GaussianHMM] = None
        self._hmm_fitted = False

        # GARCH model parameters (fitted online)
        self.garch_omega = 0.000001
        self.garch_alpha = 0.1
        self.garch_beta = 0.85
        self.current_variance = 0.0001

        # State mapping (fitted during training)
        self.state_to_regime: Dict[int, Regime] = {}

        # Performance tracking
        self.detection_times: deque = deque(maxlen=1000)
        self.regime_history: deque = deque(maxlen=1000)
        self.price_history: deque = deque(maxlen=feature_window * 2)

        # Fallback mode if libraries not available
        self._use_fallback = not HMMLEARN_AVAILABLE

    def fit(self, prices: np.ndarray) -> bool:
        """
        Fit HMM model on historical price data.

        Args:
            prices: Array of historical prices

        Returns:
            True if fitting successful
        """
        if len(prices) < self.feature_window * 2:
            print(f"[REGIME] Insufficient data: {len(prices)} < {self.feature_window * 2}")
            return False

        # Compute log returns
        log_returns = np.diff(np.log(prices))
        log_returns = log_returns[np.isfinite(log_returns)]

        if len(log_returns) < self.feature_window:
            print(f"[REGIME] Insufficient returns: {len(log_returns)}")
            return False

        if self._use_fallback:
            return self._fit_fallback(log_returns)

        return self._fit_hmm(log_returns)

    def _fit_hmm(self, log_returns: np.ndarray) -> bool:
        """Fit Gaussian HMM model."""
        try:
            # Prepare features: returns and squared returns (volatility proxy)
            features = np.column_stack([
                log_returns,
                log_returns ** 2
            ])

            # Fit HMM
            self.hmm = GaussianHMM(
                n_components=self.n_states,
                covariance_type="full",
                n_iter=100,
                random_state=42,
                init_params='stmc'  # Initialize all parameters
            )

            self.hmm.fit(features)
            self._hmm_fitted = True

            # Map HMM states to regimes based on state characteristics
            self._map_states_to_regimes()

            print(f"[REGIME] HMM fitted: converged={self.hmm.monitor_.converged}, "
                  f"log-likelihood={self.hmm.score(features):.2f}")

            return True

        except Exception as e:
            print(f"[REGIME] HMM fitting failed: {e}")
            self._use_fallback = True
            return self._fit_fallback(log_returns)

    def _fit_fallback(self, log_returns: np.ndarray) -> bool:
        """
        Fallback regime detection using simple heuristics.

        Used when hmmlearn is not available.
        """
        print("[REGIME] Using fallback heuristic regime detection")

        # Compute regime characteristics
        vol = np.std(log_returns)
        mean_ret = np.mean(log_returns)

        # Simple thresholds for regime classification
        self._fallback_thresholds = {
            'high_vol': vol * 2.0,
            'trend': np.abs(mean_ret) * 3.0
        }

        return True

    def _map_states_to_regimes(self):
        """Map HMM states to regime types based on state means."""
        if self.hmm is None:
            return

        for state in range(self.n_states):
            mean_return = self.hmm.means_[state][0]
            mean_vol_proxy = self.hmm.means_[state][1]

            # Classify based on return and volatility characteristics
            if mean_vol_proxy > np.percentile(self.hmm.means_[:, 1], 66):
                self.state_to_regime[state] = Regime.HIGH_VOLATILITY
            elif np.abs(mean_return) > np.std(self.hmm.means_[:, 0]):
                self.state_to_regime[state] = Regime.TRENDING
            else:
                self.state_to_regime[state] = Regime.MEAN_REVERTING

        print(f"[REGIME] State mapping: {self.state_to_regime}")

    def detect(self, price: float) -> RegimePrediction:
        """
        Detect current market regime from price.

        Args:
            price: Current price

        Returns:
            RegimePrediction with regime, confidence, and probabilities
        """
        start_time = time.time()

        # Update feature extractor
        features = self.feature_extractor.update(price)

        if features is None:
            return RegimePrediction(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                probabilities={r: 0.33 for r in Regime if r != Regime.UNKNOWN},
                volatility_forecast=np.sqrt(self.current_variance),
                timestamp=start_time
            )

        # Store price for later analysis
        self.price_history.append(price)

        # Detect regime
        if self._use_fallback:
            prediction = self._detect_fallback(features)
        else:
            prediction = self._detect_hmm(features)

        # Update volatility forecast with GARCH
        prediction.volatility_forecast = self._update_garch(features)

        # Track performance
        detection_time = time.time() - start_time
        self.detection_times.append(detection_time)
        self.regime_history.append(prediction.regime)

        prediction.timestamp = time.time()

        return prediction

    def _detect_hmm(self, features: RegimeFeatures) -> RegimePrediction:
        """Detect regime using HMM."""
        if not self._hmm_fitted or self.hmm is None:
            return self._detect_fallback(features)

        try:
            # Prepare observation
            obs = np.array([[features.mean_return, features.volatility ** 2]])

            # Get state probabilities
            log_prob, state = self.hmm.decode(obs, algorithm="viterbi")
            state_probs = self._get_state_probabilities(obs[0])

            # Map to regime
            regime = self.state_to_regime.get(state[0], Regime.UNKNOWN)

            # Compute confidence as max probability
            confidence = np.max(state_probs)

            # Convert state probabilities to regime probabilities
            regime_probs = {r: 0.0 for r in Regime if r != Regime.UNKNOWN}
            for s, prob in enumerate(state_probs):
                r = self.state_to_regime.get(s, Regime.UNKNOWN)
                if r != Regime.UNKNOWN:
                    regime_probs[r] += prob

            return RegimePrediction(
                regime=regime,
                confidence=float(confidence),
                probabilities=regime_probs,
                volatility_forecast=0.0,  # Will be updated by GARCH
                timestamp=0.0
            )

        except Exception as e:
            print(f"[REGIME] HMM detection failed: {e}")
            return self._detect_fallback(features)

    def _get_state_probabilities(self, obs: np.ndarray) -> np.ndarray:
        """Get probability distribution over hidden states."""
        if self.hmm is None:
            return np.ones(self.n_states) / self.n_states

        # Compute likelihood for each state
        log_probs = np.zeros(self.n_states)
        for state in range(self.n_states):
            mean = self.hmm.means_[state]
            cov = self.hmm.covars_[state]

            # Multivariate Gaussian log-likelihood
            diff = obs - mean
            try:
                log_prob = -0.5 * (np.log(np.linalg.det(cov)) +
                                   diff @ np.linalg.inv(cov) @ diff.T +
                                   len(obs) * np.log(2 * np.pi))
                log_probs[state] = log_prob
            except np.linalg.LinAlgError:
                log_probs[state] = -1e10

        # Convert to probabilities
        log_probs -= np.max(log_probs)  # Numerical stability
        probs = np.exp(log_probs)
        probs /= np.sum(probs)

        return probs

    def _detect_fallback(self, features: RegimeFeatures) -> RegimePrediction:
        """
        Fallback regime detection using heuristics.

        Uses:
        - Volatility level for high volatility detection
        - Autocorrelation and momentum for trend/mean-reversion
        """
        # High volatility detection
        annualized_vol = features.volatility * np.sqrt(252 * 24 * 60)

        if hasattr(self, '_fallback_thresholds'):
            high_vol_threshold = self._fallback_thresholds['high_vol'] * np.sqrt(252 * 24 * 60)
        else:
            high_vol_threshold = 0.5  # 50% annualized volatility

        if annualized_vol > high_vol_threshold:
            regime = Regime.HIGH_VOLATILITY
            confidence = min(annualized_vol / (high_vol_threshold * 2), 1.0)
        elif np.abs(features.price_momentum) > 0.5 and features.autocorr_1 > 0.1:
            # Strong momentum + positive autocorrelation = trending
            regime = Regime.TRENDING
            confidence = min(np.abs(features.price_momentum), 1.0)
        else:
            # Default to mean-reverting
            regime = Regime.MEAN_REVERTING
            confidence = 0.5 + 0.5 * np.abs(features.autocorr_1)

        # Build probability distribution
        probs = {r: 0.1 for r in Regime if r != Regime.UNKNOWN}
        probs[regime] = confidence

        # Normalize
        total = sum(probs.values())
        probs = {k: v / total for k, v in probs.items()}

        return RegimePrediction(
            regime=regime,
            confidence=confidence,
            probabilities=probs,
            volatility_forecast=annualized_vol,
            timestamp=0.0
        )

    def _update_garch(self, features: RegimeFeatures) -> float:
        """
        Update GARCH(1,1) volatility forecast.

        Returns annualized volatility forecast.
        """
        if not ARCH_AVAILABLE:
            # Simple EWMA fallback
            ret_sq = features.mean_return ** 2
            self.current_variance = 0.94 * self.current_variance + 0.06 * ret_sq
            return np.sqrt(self.current_variance * 252 * 24 * 60)

        # Update GARCH parameters online
        ret_sq = features.mean_return ** 2

        # GARCH(1,1) update
        self.current_variance = (
            self.garch_omega +
            self.garch_alpha * ret_sq +
            self.garch_beta * self.current_variance
        )

        # Annualize
        annualized_vol = np.sqrt(self.current_variance * 252 * 24 * 60)

        return float(annualized_vol)

    def predict_proba(self, features: Optional[RegimeFeatures] = None) -> np.ndarray:
        """
        Get probability distribution over regimes.

        Args:
            features: Pre-computed features (optional)

        Returns:
            Array of probabilities [trending, mean_reverting, high_vol]
        """
        if features is None:
            # Use last known features or return uniform
            if len(self.regime_history) > 0:
                last_regime = self.regime_history[-1]
                probs = np.zeros(3)
                if last_regime == Regime.TRENDING:
                    probs[0] = 1.0
                elif last_regime == Regime.MEAN_REVERTING:
                    probs[1] = 1.0
                elif last_regime == Regime.HIGH_VOLATILITY:
                    probs[2] = 1.0
                else:
                    probs = np.ones(3) / 3
                return probs
            return np.ones(3) / 3

        if self._use_fallback:
            pred = self._detect_fallback(features)
        else:
            pred = self._detect_hmm(features)

        return np.array([
            pred.probabilities.get(Regime.TRENDING, 0.33),
            pred.probabilities.get(Regime.MEAN_REVERTING, 0.33),
            pred.probabilities.get(Regime.HIGH_VOLATILITY, 0.33)
        ])

    def get_avg_detection_time(self) -> float:
        """Get average detection latency in milliseconds."""
        if not self.detection_times:
            return 0.0
        return np.mean(self.detection_times) * 1000

    def get_regime_distribution(self) -> Dict[Regime, float]:
        """Get distribution of regimes in history."""
        if not self.regime_history:
            return {r: 0.0 for r in Regime}

        counts = {r: 0 for r in Regime}
        for r in self.regime_history:
            counts[r] += 1

        total = len(self.regime_history)
        return {r: c / total for r, c in counts.items()}

    def reset(self):
        """Reset detector state."""
        self.feature_extractor.reset()
        self.hmm = None
        self._hmm_fitted = False
        self.state_to_regime.clear()
        self.detection_times.clear()
        self.regime_history.clear()
        self.price_history.clear()
        self.current_variance = 0.0001


def generate_synthetic_regimes(n_samples: int = 1000, seed: int = 42) -> Tuple[np.ndarray, List[Regime]]:
    """
    Generate synthetic price data with known regimes for testing.

    Returns:
        prices: Array of prices
        true_regimes: List of true regime labels
    """
    np.random.seed(seed)

    prices = [100.0]
    regimes = []

    # Generate 3 segments with different characteristics
    segment_size = n_samples // 3

    # Segment 1: Trending up
    for i in range(segment_size):
        ret = np.random.normal(0.001, 0.01)
        prices.append(prices[-1] * (1 + ret))
        regimes.append(Regime.TRENDING)

    # Segment 2: Mean-reverting
    mean = prices[-1]
    for i in range(segment_size):
        deviation = prices[-1] - mean
        ret = np.random.normal(-0.001 * deviation / mean, 0.008)
        prices.append(prices[-1] * (1 + ret))
        regimes.append(Regime.MEAN_REVERTING)

    # Segment 3: High volatility
    for i in range(segment_size):
        ret = np.random.normal(0.0, 0.03)
        prices.append(prices[-1] * (1 + ret))
        regimes.append(Regime.HIGH_VOLATILITY)

    # Handle remainder if n_samples not divisible by 3
    remainder = n_samples - len(regimes)
    for i in range(remainder):
        ret = np.random.normal(0.0, 0.03)
        prices.append(prices[-1] * (1 + ret))
        regimes.append(Regime.HIGH_VOLATILITY)

    return np.array(prices), regimes


if __name__ == "__main__":
    # Test regime detector
    print("Testing MarketRegimeDetector...")

    # Generate synthetic data
    prices, true_regimes = generate_synthetic_regimes(n_samples=900)

    # Split into train/test
    train_size = 600
    train_prices = prices[:train_size]
    test_prices = prices[train_size:]
    test_regimes = true_regimes[train_size:]

    # Create and fit detector
    detector = MarketRegimeDetector(n_states=3)

    print(f"\nFitting on {len(train_prices)} samples...")
    success = detector.fit(train_prices)
    print(f"Fit successful: {success}")

    # Test detection
    print(f"\nTesting on {len(test_prices)} samples...")
    predictions = []

    for price in test_prices:
        pred = detector.detect(price)
        predictions.append(pred.regime)

    # Calculate accuracy
    correct = sum(1 for p, t in zip(predictions, test_regimes) if p == t)
    accuracy = correct / len(test_regimes)

    print(f"\nAccuracy: {accuracy:.2%}")
    print(f"Average detection time: {detector.get_avg_detection_time():.3f}ms")

    # Show regime distribution
    dist = detector.get_regime_distribution()
    print(f"\nRegime distribution:")
    for regime, pct in dist.items():
        if regime != Regime.UNKNOWN:
            print(f"  {regime.value}: {pct:.1%}")

    print("\nTest complete!")
