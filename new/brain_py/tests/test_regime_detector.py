"""
test_regime_detector.py - Unit tests for regime detection system.

Coverage targets:
- RegimeFeatureExtractor: > 80%
- MarketRegimeDetector: > 80%
- Regime classification accuracy: > 60%
"""

import unittest
import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regime_detector import (
    MarketRegimeDetector, Regime, RegimePrediction,
    generate_synthetic_regimes
)
from features.regime_features import RegimeFeatureExtractor, RegimeFeatures


class TestRegimeFeatureExtractor(unittest.TestCase):
    """Test feature extraction functionality."""

    def setUp(self):
        self.extractor = RegimeFeatureExtractor(window=50, min_samples=20)

    def test_initialization(self):
        """Test extractor initialization."""
        self.assertEqual(self.extractor.window, 50)
        self.assertEqual(self.extractor.min_samples, 20)
        self.assertEqual(len(self.extractor.prices), 0)

    def test_update_insufficient_data(self):
        """Test update with insufficient data returns None."""
        for i in range(10):
            result = self.extractor.update(100.0 + i)

        # Should return None with insufficient data
        self.assertIsNone(result)

    def test_update_sufficient_data(self):
        """Test update with sufficient data returns features."""
        np.random.seed(42)
        price = 100.0

        for _ in range(30):
            price *= (1 + np.random.normal(0, 0.01))
            result = self.extractor.update(price)

        # Should return features with sufficient data
        self.assertIsNotNone(result)
        self.assertIsInstance(result, RegimeFeatures)

    def test_feature_computation(self):
        """Test feature computation correctness."""
        np.random.seed(42)
        price = 100.0

        for _ in range(50):
            price *= (1 + np.random.normal(0.001, 0.01))
            self.extractor.update(price)

        features = self.extractor._compute_features()

        # Check all features are finite
        self.assertTrue(np.isfinite(features.volatility))
        self.assertTrue(np.isfinite(features.mean_return))
        self.assertTrue(np.isfinite(features.skewness))
        self.assertTrue(np.isfinite(features.kurtosis))
        self.assertTrue(np.isfinite(features.price_momentum))
        self.assertTrue(np.isfinite(features.volatility_of_vol))
        self.assertTrue(np.isfinite(features.autocorr_1))

        # Check volatility is positive
        self.assertGreater(features.volatility, 0)

    def test_skewness_kurtosis(self):
        """Test skewness and kurtosis computation."""
        # Symmetric distribution should have near-zero skewness
        symmetric = np.random.normal(0, 1, 1000)
        skew = self.extractor._compute_skewness(symmetric)
        self.assertAlmostEqual(skew, 0, delta=0.3)

        # Normal distribution should have near-zero excess kurtosis
        kurt = self.extractor._compute_kurtosis(symmetric)
        self.assertAlmostEqual(kurt, 0, delta=0.5)

    def test_momentum_computation(self):
        """Test momentum computation."""
        # Upward trend
        up_prices = np.linspace(100, 150, 50)
        self.extractor.prices.clear()
        for p in up_prices:
            self.extractor.prices.append(p)

        momentum = self.extractor._compute_momentum()
        self.assertGreater(momentum, 0)

        # Downward trend
        down_prices = np.linspace(150, 100, 50)
        self.extractor.prices.clear()
        for p in down_prices:
            self.extractor.prices.append(p)

        momentum = self.extractor._compute_momentum()
        self.assertLess(momentum, 0)

    def test_autocorrelation(self):
        """Test autocorrelation computation."""
        # Strong positive autocorrelation
        ar1 = np.zeros(100)
        ar1[0] = np.random.normal()
        for i in range(1, 100):
            ar1[i] = 0.9 * ar1[i-1] + np.random.normal(0, 0.1)

        autocorr = self.extractor._compute_autocorr(ar1)
        self.assertGreater(autocorr, 0.5)

        # White noise should have near-zero autocorrelation
        white = np.random.normal(0, 1, 1000)
        autocorr = self.extractor._compute_autocorr(white)
        self.assertAlmostEqual(autocorr, 0, delta=0.1)

    def test_feature_vector(self):
        """Test feature vector generation."""
        np.random.seed(42)
        price = 100.0

        for _ in range(50):
            price *= (1 + np.random.normal(0.001, 0.01))
            self.extractor.update(price)

        features = self.extractor._compute_features()
        vector = self.extractor.get_feature_vector(features)

        self.assertEqual(len(vector), 7)
        self.assertTrue(np.all(np.isfinite(vector)))

    def test_reset(self):
        """Test reset functionality."""
        np.random.seed(42)
        price = 100.0

        for _ in range(50):
            price *= (1 + np.random.normal(0.001, 0.01))
            self.extractor.update(price)

        self.assertGreater(len(self.extractor.prices), 0)

        self.extractor.reset()

        self.assertEqual(len(self.extractor.prices), 0)
        self.assertEqual(len(self.extractor.returns), 0)

    def test_invalid_price(self):
        """Test handling of invalid prices."""
        result = self.extractor.update(-100)
        self.assertIsNone(result)

        result = self.extractor.update(np.nan)
        self.assertIsNone(result)

        result = self.extractor.update(np.inf)
        self.assertIsNone(result)


class TestMarketRegimeDetector(unittest.TestCase):
    """Test regime detector functionality."""

    def setUp(self):
        self.detector = MarketRegimeDetector(n_states=3, feature_window=50)

    def test_initialization(self):
        """Test detector initialization."""
        self.assertEqual(self.detector.n_states, 3)
        self.assertEqual(self.detector.feature_window, 50)
        self.assertFalse(self.detector._hmm_fitted)

    def test_fit_insufficient_data(self):
        """Test fit with insufficient data."""
        prices = np.random.normal(100, 1, 50)
        success = self.detector.fit(prices)
        self.assertFalse(success)

    def test_fit_sufficient_data(self):
        """Test fit with sufficient data."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        success = self.detector.fit(prices)
        self.assertTrue(success)

    def test_detect_before_fit(self):
        """Test detection before fitting."""
        pred = self.detector.detect(100.0)

        self.assertIsInstance(pred, RegimePrediction)
        self.assertIn(pred.regime, Regime)

    def test_detect_after_fit(self):
        """Test detection after fitting."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        # Feed some prices
        for price in prices[-50:]:
            pred = self.detector.detect(price)

        self.assertIsInstance(pred, RegimePrediction)
        self.assertGreaterEqual(pred.confidence, 0)
        self.assertLessEqual(pred.confidence, 1)

    def test_prediction_structure(self):
        """Test prediction has correct structure."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        for price in prices[-20:]:
            pred = self.detector.detect(price)

            # Check all required fields
            self.assertIsInstance(pred.regime, Regime)
            self.assertIsInstance(pred.confidence, float)
            self.assertIsInstance(pred.probabilities, dict)
            self.assertIsInstance(pred.volatility_forecast, float)
            self.assertIsInstance(pred.timestamp, float)

            # Check confidence bounds
            self.assertGreaterEqual(pred.confidence, 0)
            self.assertLessEqual(pred.confidence, 1)

            # Check probabilities sum to ~1
            prob_sum = sum(pred.probabilities.values())
            self.assertAlmostEqual(prob_sum, 1.0, delta=0.02)

            # Check volatility forecast is positive
            self.assertGreaterEqual(pred.volatility_forecast, 0)

    def test_predict_proba(self):
        """Test probability prediction."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        # Feed prices to build features
        for price in prices[-100:]:
            self.detector.detect(price)

        proba = self.detector.predict_proba()

        self.assertEqual(len(proba), 3)
        self.assertAlmostEqual(np.sum(proba), 1.0, delta=0.01)
        self.assertTrue(np.all(proba >= 0))
        self.assertTrue(np.all(proba <= 1))

    def test_detection_latency(self):
        """Test detection latency is under 1 second."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        # Warm up
        for price in prices[-50:]:
            self.detector.detect(price)

        avg_time = self.detector.get_avg_detection_time()
        self.assertLess(avg_time, 1000)  # Less than 1000ms

    def test_regime_distribution(self):
        """Test regime distribution tracking."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        for price in prices[-100:]:
            self.detector.detect(price)

        dist = self.detector.get_regime_distribution()

        self.assertIn(Regime.TRENDING, dist)
        self.assertIn(Regime.MEAN_REVERTING, dist)
        self.assertIn(Regime.HIGH_VOLATILITY, dist)
        self.assertIn(Regime.UNKNOWN, dist)

        # Check probabilities sum to 1
        total = sum(dist.values())
        self.assertAlmostEqual(total, 1.0, delta=0.01)

    def test_reset(self):
        """Test detector reset."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        for price in prices[-50:]:
            self.detector.detect(price)

        self.assertGreater(len(self.detector.regime_history), 0)

        self.detector.reset()

        self.assertIsNone(self.detector.hmm)
        self.assertFalse(self.detector._hmm_fitted)
        self.assertEqual(len(self.detector.regime_history), 0)

    def test_garch_update(self):
        """Test GARCH volatility update."""
        prices, _ = generate_synthetic_regimes(n_samples=300)
        self.detector.fit(prices)

        volatilities = []
        for price in prices[-100:]:
            pred = self.detector.detect(price)
            volatilities.append(pred.volatility_forecast)

        # Check volatilities are positive and finite
        self.assertTrue(all(np.isfinite(v) for v in volatilities))
        self.assertTrue(all(v >= 0 for v in volatilities))


class TestRegimeClassificationAccuracy(unittest.TestCase):
    """Test regime classification accuracy meets > 60% target."""

    def test_synthetic_data_accuracy(self):
        """Test accuracy on synthetic data with known regimes."""
        prices, true_regimes = generate_synthetic_regimes(n_samples=900)

        # Split train/test
        train_size = 600
        train_prices = prices[:train_size]
        test_prices = prices[train_size:]
        test_regimes = true_regimes[train_size:]

        # Fit detector
        detector = MarketRegimeDetector(n_states=3)
        success = detector.fit(train_prices)
        self.assertTrue(success)

        # Test detection
        predictions = []
        for price in test_prices:
            pred = detector.detect(price)
            predictions.append(pred.regime)

        # Calculate accuracy
        correct = sum(1 for p, t in zip(predictions, test_regimes) if p == t)
        accuracy = correct / len(test_regimes)

        print(f"\nRegime classification accuracy: {accuracy:.2%}")
        print(f"Target: > 60%")

        # Check accuracy meets target
        self.assertGreater(accuracy, 0.60)


class TestSyntheticDataGeneration(unittest.TestCase):
    """Test synthetic data generation."""

    def test_generation(self):
        """Test synthetic regime data generation."""
        prices, regimes = generate_synthetic_regimes(n_samples=300)

        self.assertEqual(len(prices), 301)  # n_samples + 1 (starting price)
        self.assertEqual(len(regimes), 300)  # regimes only for generated returns

        # Check all regimes are present
        self.assertIn(Regime.TRENDING, regimes)
        self.assertIn(Regime.MEAN_REVERTING, regimes)
        self.assertIn(Regime.HIGH_VOLATILITY, regimes)

        # Check prices are positive
        self.assertTrue(np.all(prices > 0))

    def test_regime_characteristics(self):
        """Test synthetic data has correct regime characteristics."""
        prices, regimes = generate_synthetic_regimes(n_samples=900)

        # Split by regime
        trending_returns = []
        meanrev_returns = []
        highvol_returns = []

        for i in range(1, len(prices)):
            ret = np.log(prices[i] / prices[i-1])
            regime_idx = min(i - 1, len(regimes) - 1)  # Handle index mismatch
            if regimes[regime_idx] == Regime.TRENDING:
                trending_returns.append(ret)
            elif regimes[regime_idx] == Regime.MEAN_REVERTING:
                meanrev_returns.append(ret)
            elif regimes[regime_idx] == Regime.HIGH_VOLATILITY:
                highvol_returns.append(ret)

        # High volatility should have highest volatility
        trending_vol = np.std(trending_returns)
        meanrev_vol = np.std(meanrev_returns)
        highvol_vol = np.std(highvol_returns)

        self.assertGreater(highvol_vol, trending_vol)
        self.assertGreater(highvol_vol, meanrev_vol)

        # Trending should have non-zero mean return
        trending_mean = np.mean(trending_returns)
        self.assertGreater(np.abs(trending_mean), 0.0001)


def run_tests():
    """Run all tests and report coverage."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestRegimeFeatureExtractor))
    suite.addTests(loader.loadTestsFromTestCase(TestMarketRegimeDetector))
    suite.addTests(loader.loadTestsFromTestCase(TestRegimeClassificationAccuracy))
    suite.addTests(loader.loadTestsFromTestCase(TestSyntheticDataGeneration))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests passed!")
    else:
        print("\nSome tests failed!")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
