"""
integrator.py
A/B Testing Integration with Live Trading System

Integrates:
- Model A/B testing (different model versions)
- Strategy A/B testing (different strategy parameters)
- Integration with Meta-Agent dynamic selection
- Real-time result tracking
- Automatic conclusion and switching
"""

import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from threading import Lock

from .core import (
    ABTest,
    ABTestConfig,
    ABTestVariant,
    ABTestStatistics,
    SplitStrategyType,
)


@dataclass
class ModelABTestConfig:
    """Configuration for model A/B test"""
    test_name: str
    control_model_id: str      # Control (baseline) model ID
    test_model_id: str        # Variant (new) model ID
    traffic_split_pct: float = 0.5  # Percentage of traffic to test model
    min_sample_size: int = 100
    significance_level: float = 0.05
    max_duration_hours: float = 168.0  # 7 days
    result_dir: str = "./ab_test_results"
    auto_switch: bool = True  # Auto-switch if variant is significantly better


class ModelABTest:
    """A/B test for comparing two model versions"""

    def __init__(self, config: ModelABTestConfig):
        self._config = config
        self._lock = Lock()

        # Create variants
        variants = [
            ABTestVariant(
                name="control",
                description=f"Control model {config.control_model_id}",
                traffic_pct=1.0 - config.traffic_split_pct,
                version=config.control_model_id,
                is_control=True
            ),
            ABTestVariant(
                name="variant",
                description=f"Test model {config.test_model_id}",
                traffic_pct=config.traffic_split_pct,
                version=config.test_model_id,
                is_control=False
            )
        ]

        # Create AB test config
        ab_config = ABTestConfig(
            test_name=config.test_name,
            description=f"Model A/B test: {config.control_model_id} vs {config.test_model_id}",
            strategy=SplitStrategyType.FIXED,
            variants=variants,
            min_sample_size=config.min_sample_size,
            significance_level=config.significance_level,
            max_duration_hours=config.max_duration_hours,
            result_dir=config.result_dir,
            enable_logging=True
        )

        self._ab_test = ABTest(ab_config)
        self._started = False
        self._model_map = {
            "control": config.control_model_id,
            "variant": config.test_model_id
        }

    def start(self) -> Optional[Exception]:
        """Start the model A/B test"""
        with self._lock:
            if self._started:
                return Exception("test already started")
            err = self._ab_test.start()
            if err is None:
                self._started = True
            return err

    def stop(self) -> Optional[Exception]:
        """Stop the test"""
        with self._lock:
            if not self._started:
                return None
            err = self._ab_test.stop()
            self._started = False
            return err

    def select_model(self) -> Tuple[str, str]:
        """Select which model to use for this prediction

        Returns:
            (variant_name, model_id)
        """
        with self._lock:
            if not self._started:
                return "control", self._model_map["control"]
            variant = self._ab_test.select_variant()
            return variant.name, self._model_map[variant.name]

    def record_prediction_result(self, variant_name: str, pnl: float,
                                  is_win: bool, alpha_bps: float = 0.0,
                                  latency_ms: float = 0.0) -> None:
        """Record the result of a prediction"""
        with self._lock:
            self._ab_test.record_result(variant_name, pnl, is_win, alpha_bps)

    def check_completion(self) -> Tuple[bool, str]:
        """Check if test should complete"""
        return self._ab_test.check_completion()

    def get_statistics(self) -> Optional[ABTestStatistics]:
        """Get current statistics"""
        return self._ab_test.calculate_statistics()

    def get_conclusion(self) -> str:
        """Get test conclusion"""
        return self._ab_test.get_conclusion()

    def should_auto_switch(self) -> Tuple[bool, str]:
        """Check if we should auto-switch to the variant"""
        if not self._config.auto_switch:
            return False, "auto-switch disabled"

        complete, reason = self.check_completion()
        if not complete:
            return False, reason

        stats = self.get_statistics()
        if stats is None or not stats.comparisons:
            return False, "no statistics available"

        comp = stats.comparisons[0]
        if comp.significant and comp.is_better:
            return True, f"Variant is significantly better (p={comp.p_value:.4f})"

        return False, f"No significant improvement: p={comp.p_value:.4f}" if comp.significant else "Not significant"


@dataclass
class StrategyABTestConfig:
    """Configuration for strategy A/B test"""
    test_name: str
    variants: List[Dict[str, Any]]  # Each: name, description, params, is_control
    strategy: int = SplitStrategyType.FIXED
    min_sample_size: int = 100
    significance_level: float = 0.05
    max_duration_hours: float = 168.0
    result_dir: str = "./ab_test_results"


@dataclass
class StrategyVariant:
    """Strategy variant for A/B test"""
    name: str
    description: str
    parameters: Dict[str, Any]
    is_control: bool
    traffic_pct: float
    strategy_factory: Callable[[Dict[str, Any]], Any]


class StrategyABTest:
    """A/B test for comparing different strategy variants"""

    def __init__(self, config: StrategyABTestConfig):
        self._config = config
        self._lock = Lock()

        # Build variants
        ab_variants: List[ABTestVariant] = []
        self._strategy_variants: Dict[str, StrategyVariant] = {}

        total_traffic = 0.0
        for v in config.variants:
            traffic_pct = v.get("traffic_pct", 1.0 / len(config.variants))
            total_traffic += traffic_pct

            sv = StrategyVariant(
                name=v["name"],
                description=v.get("description", ""),
                parameters=v.get("parameters", {}),
                is_control=v.get("is_control", False),
                traffic_pct=traffic_pct,
                strategy_factory=v.get("strategy_factory", lambda p: None)
            )

            av = ABTestVariant(
                name=v["name"],
                description=sv.description,
                traffic_pct=traffic_pct,
                version="1.0",
                is_control=sv.is_control
            )

            ab_variants.append(av)
            self._strategy_variants[v["name"]] = sv

        # Normalize traffic
        if abs(total_traffic - 1.0) > 0.01:
            for av in ab_variants:
                av.traffic_pct /= total_traffic

        # Create AB test
        ab_config = ABTestConfig(
            test_name=config.test_name,
            description=f"Strategy A/B test with {len(ab_variants)} variants",
            strategy=config.strategy,
            variants=ab_variants,
            min_sample_size=config.min_sample_size,
            significance_level=config.significance_level,
            max_duration_hours=config.max_duration_hours,
            result_dir=config.result_dir,
            enable_logging=True
        )

        self._ab_test = ABTest(ab_config)
        self._started = False

    def start(self) -> Optional[Exception]:
        """Start the strategy A/B test"""
        with self._lock:
            if self._started:
                return Exception("test already started")
            err = self._ab_test.start()
            if err is None:
                self._started = True
            return err

    def stop(self) -> Optional[Exception]:
        """Stop the test"""
        with self._lock:
            if not self._started:
                return None
            err = self._ab_test.stop()
            self._started = False
            return err

    def select_strategy(self) -> Tuple[str, Any]:
        """Select strategy variant and instantiate

        Returns:
            (variant_name, strategy_instance)
        """
        with self._lock:
            if not self._started:
                # Return control if not started
                for name, sv in self._strategy_variants.items():
                    if sv.is_control:
                        return name, sv.strategy_factory(sv.parameters)
                # Fallback to first
                first = list(self._strategy_variants.values())[0]
                return first.name, first.strategy_factory(first.parameters)

            variant = self._ab_test.select_variant()
            sv = self._strategy_variants.get(variant.name)
            if sv is None:
                # Fallback to control
                for name, sv_fallback in self._strategy_variants.items():
                    if sv_fallback.is_control:
                        return name, sv_fallback.strategy_factory(sv_fallback.parameters)

            instance = sv.strategy_factory(sv.parameters)
            return variant.name, instance

    def record_result(self, variant_name: str, pnl: float, is_win: bool,
                      alpha_bps: float = 0.0) -> None:
        """Record trading result for a variant"""
        with self._lock:
            self._ab_test.record_result(variant_name, pnl, is_win, alpha_bps)

    def get_current_results(self) -> Dict[str, Any]:
        """Get current results for all variants"""
        results = self._ab_test.get_all_results()
        stats = self._ab_test.calculate_statistics()

        output: Dict[str, Any] = {}
        for name, res in results.items():
            output[name] = {
                "total_trades": res.total_trades,
                "total_pnl": res.total_pnl,
                "win_rate": res.win_rate,
                "cumulative_alpha_bps": res.cumulative_alpha_bps
            }

        if stats:
            output["statistics"] = {
                "comparisons": [c.__dict__ for c in stats.comparisons]
            }

        output["conclusion"] = self._ab_test.get_conclusion()
        return output

    def get_conclusion(self) -> str:
        """Get test conclusion"""
        return self._ab_test.get_conclusion()


class ABTestIntegrator:
    """
    A/B Testing Integrator for live trading system

    Manages multiple concurrent A/B tests:
    - Model version comparison
    - Strategy parameter comparison
    - Integrates with live_integrator main loop
    """

    def __init__(self, result_dir: str = "./ab_test_results"):
        self._result_dir = result_dir
        self._model_tests: Dict[str, ModelABTest] = {}
        self._strategy_tests: Dict[str, StrategyABTest] = {}
        self._lock = Lock()
        os.makedirs(result_dir, exist_ok=True)

    def register_model_ab_test(self, config: ModelABTestConfig) -> ModelABTest:
        """Register a new model A/B test"""
        with self._lock:
            config.result_dir = self._result_dir
            test = ModelABTest(config)
            self._model_tests[config.test_name] = test
            return test

    def register_strategy_ab_test(self, config: StrategyABTestConfig) -> StrategyABTest:
        """Register a new strategy A/B test"""
        with self._lock:
            config.result_dir = self._result_dir
            test = StrategyABTest(config)
            self._strategy_tests[config.test_name] = test
            return test

    def get_model_test(self, test_name: str) -> Optional[ModelABTest]:
        """Get a model A/B test by name"""
        with self._lock:
            return self._model_tests.get(test_name)

    def get_strategy_test(self, test_name: str) -> Optional[StrategyABTest]:
        """Get a strategy A/B test by name"""
        with self._lock:
            return self._strategy_tests.get(test_name)

    def start_all(self) -> List[Exception]:
        """Start all registered tests"""
        errors: List[Exception] = []
        with self._lock:
            for test in self._model_tests.values():
                err = test.start()
                if err:
                    errors.append(err)
            for test in self._strategy_tests.values():
                err = test.start()
                if err:
                    errors.append(err)
        return errors

    def stop_all(self) -> List[Exception]:
        """Stop all registered tests"""
        errors: List[Exception] = []
        with self._lock:
            for test in self._model_tests.values():
                err = test.stop()
                if err:
                    errors.append(err)
            for test in self._strategy_tests.values():
                err = test.stop()
                if err:
                    errors.append(err)
        return errors

    def check_all_completion(self) -> List[Tuple[str, bool, str]]:
        """Check if all tests should complete"""
        results: List[Tuple[str, bool, str]] = []
        with self._lock:
            for name, test in self._model_tests.items():
                complete, reason = test.check_completion()
                results.append((name, complete, reason))
            for name, test in self._strategy_tests.items():
                complete, reason = test.check_completion()
                results.append((name, complete, reason))
        return results

    def get_all_conclusions(self) -> Dict[str, str]:
        """Get conclusions for all tests"""
        conclusions: Dict[str, str] = {}
        with self._lock:
            for name, test in self._model_tests.items():
                conclusions[name] = test.get_conclusion()
            for name, test in self._strategy_tests.items():
                conclusions[name] = test.get_conclusion()
        return conclusions

    def save_all_results(self) -> None:
        """Save results for all tests"""
        with self._lock:
            for test in self._model_tests.values():
                test._ab_test.save_results()
            for test in self._strategy_tests.values():
                test._ab_test.save_results()

    def has_active_tests(self) -> bool:
        """Check if there are any active tests"""
        with self._lock:
            for test in self._model_tests.values():
                if test._started:
                    return True
            for test in self._strategy_tests.values():
                if test._started:
                    return True
            return False

    def get_status(self) -> Dict[str, Any]:
        """Get integrator status"""
        with self._lock:
            return {
                "active_model_tests": len([t for t in self._model_tests.values() if t._started]),
                "total_model_tests": len(self._model_tests),
                "active_strategy_tests": len([t for t in self._strategy_tests.values() if t._started]),
                "total_strategy_tests": len(self._strategy_tests),
                "result_dir": self._result_dir
            }
