"""
core.py
Core A/B Testing framework implementation in Python
Mirrors the Go implementation for consistency
"""

import json
import math
import os
import pathlib
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from threading import Lock


class SplitStrategyType:
    """Traffic split strategy type"""
    FIXED = 0       # Fixed percentage
    CANARY = 1      # Canary rollout (gradual increase)
    ADAPTIVE = 2    # Adaptive based on performance


@dataclass
class ABTestVariant:
    """Represents a variant in A/B test"""
    name: str
    description: str
    traffic_pct: float  # Traffic percentage [0-1]
    version: str
    is_control: bool


@dataclass
class ABTestResult:
    """Stores accumulated results for a variant"""
    variant_name: str
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    total_volume: float = 0.0
    cumulative_alpha_bps: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    start_time: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)


@dataclass
class ABTestConfig:
    """Configuration for A/B test"""
    test_name: str
    description: str
    strategy: int = SplitStrategyType.FIXED
    variants: List[ABTestVariant] = field(default_factory=list)
    min_sample_size: int = 100
    significance_level: float = 0.05  # p-value threshold
    max_duration_hours: float = 168.0  # 7 days default
    result_dir: str = "./ab_test_results"
    enable_logging: bool = True


@dataclass
class VariantComparison:
    """Comparison result between variant and control"""
    variant_name: str
    control_pnl: float
    variant_pnl: float
    diff_pnl: float
    diff_pnl_bps: float
    control_sharpe: float
    variant_sharpe: float
    diff_sharpe: float
    p_value: float
    significant: bool
    is_better: bool


@dataclass
class ABTestStatistics:
    """Aggregated statistics"""
    control: Optional[ABTestResult]
    comparisons: List[VariantComparison] = field(default_factory=list)


class ABTest:
    """Main A/B testing framework"""

    def __init__(self, config: ABTestConfig):
        self._config = config
        self._results: Dict[str, ABTestResult] = {}
        self._variants: List[ABTestVariant] = config.variants.copy()
        self._lock = Lock()
        self._start_time = time.time()
        self._running = False

        # Validate traffic sums to ~1
        total_traffic = sum(v.traffic_pct for v in self._variants)
        if abs(total_traffic - 1.0) > 0.01:
            print(f"[AB] Warning: Total traffic {total_traffic:.3f} != 1.0")

        # Count control variants
        control_count = sum(1 for v in self._variants if v.is_control)
        if control_count != 1:
            print(f"[AB] Warning: Expected 1 control variant, got {control_count}")

        # Initialize results
        now = time.time()
        for v in self._variants:
            self._results[v.name] = ABTestResult(
                variant_name=v.name,
                start_time=now
            )

    def start(self) -> Optional[Exception]:
        """Start the A/B test"""
        with self._lock:
            if self._running:
                return Exception("test already running")

            self._start_time = time.time()
            self._running = True
            print(f"[AB] Started A/B test '{self._config.test_name}' with {len(self._variants)} variants")

            # Create results directory
            if self._config.result_dir:
                pathlib.Path(self._config.result_dir).mkdir(parents=True, exist_ok=True)

            return None

    def is_running(self) -> bool:
        """Check if test is running"""
        with self._lock:
            return self._running

    def select_variant(self) -> ABTestVariant:
        """Select which variant to use for the next request"""
        with self._lock:
            # For adaptive/canary, we may adjust traffic based on current results
            # For now, use fixed random selection
            u = random.random()
            cumulative = 0.0
            for v in self._variants:
                cumulative += v.traffic_pct
                if u < cumulative:
                    return v

            # Fallback to last
            return self._variants[-1]

    def record_result(self, variant_name: str, pnl: float, is_win: bool,
                      alpha_bps: float = 0.0, volume: float = 0.0) -> None:
        """Record a result for a variant"""
        with self._lock:
            res = self._results.get(variant_name)
            if res is None:
                print(f"[AB] Warning: Result recorded for unknown variant {variant_name}")
                return

            res.total_trades += 1
            if is_win:
                res.winning_trades += 1
            res.total_pnl += pnl
            res.cumulative_alpha_bps += alpha_bps
            res.total_volume += volume
            res.last_update = time.time()

            # Recalculate win rate
            if res.total_trades > 0:
                res.win_rate = res.winning_trades / res.total_trades

            # Save periodically
            if self._config.enable_logging and res.total_trades % 10 == 0:
                self._save_results_locked()

    def get_result(self, variant_name: str) -> Optional[ABTestResult]:
        """Get current result for a variant"""
        with self._lock:
            return self._results.get(variant_name)

    def get_all_results(self) -> Dict[str, ABTestResult]:
        """Get all current results (copy)"""
        with self._lock:
            return self._results.copy()

    def check_completion(self) -> tuple[bool, str]:
        """Check if test should complete"""
        with self._lock:
            elapsed = (time.time() - self._start_time) / 3600.0
            if elapsed > self._config.max_duration_hours:
                return True, f"max duration {self._config.max_duration_hours:.1f} hours reached"

            # Check minimum sample size across all variants
            for res in self._results.values():
                if res.total_trades < self._config.min_sample_size:
                    return False, f"variant {res.variant_name} has {res.total_trades} trades, needs {self._config.min_sample_size}"

            # All variants have enough samples
            return True, "all variants reached minimum sample size"

    def calculate_statistics(self) -> Optional[ABTestStatistics]:
        """Calculate statistical significance using Welch's t-test"""
        with self._lock:
            # Find control
            control_result: Optional[ABTestResult] = None
            variants: List[ABTestResult] = []

            for name, res in self._results.items():
                variant = self._get_variant(name)
                if variant and variant.is_control:
                    control_result = res
                else:
                    variants.append(res)

            if control_result is None:
                return None

            stats = ABTestStatistics(
                control=control_result,
                comparisons=[]
            )

            # Compare each variant against control
            for variant in variants:
                comp = self._compare_variant(control_result, variant)
                stats.comparisons.append(comp)

            return stats

    def get_conclusion(self) -> str:
        """Get test conclusion as string"""
        stats = self.calculate_statistics()
        if stats is None:
            return "No control variant found"

        conclusion = []
        conclusion.append(f"A/B Test: {self._config.test_name}\n")
        conclusion.append(f"Duration: {(time.time() - self._start_time)/3600:.2f} hours")
        conclusion.append(f"Control: {stats.control.variant_name}")
        conclusion.append(f"  - Trades: {stats.control.total_trades}")
        conclusion.append(f"  - Total PnL: {stats.control.total_pnl:.4f}")
        conclusion.append(f"  - Win rate: {stats.control.win_rate*100:.2f}%\n")

        for comp in stats.comparisons:
            res = self._results.get(comp.variant_name)
            conclusion.append(f"Variant: {comp.variant_name}")
            conclusion.append(f"  - Trades: {res.total_trades if res else 'N/A'}")
            conclusion.append(f"  - Total PnL: {comp.variant_pnl:.4f} (diff: {comp.diff_pnl:.4f})")
            conclusion.append(f"  - Sharpe: {comp.variant_sharpe:.2f} vs {comp.control_sharpe:.2f} (diff: {comp.diff_sharpe:.2f})")
            conclusion.append(f"  - p-value: {comp.p_value:.4f}")
            conclusion.append(f"  - Significant: {comp.significant}")
            if comp.significant:
                if comp.is_better:
                    conclusion.append("  - ✅ Variant is significantly BETTER than control")
                else:
                    conclusion.append("  - ❌ Variant is significantly WORSE than control")
            else:
                conclusion.append("  - ⚠️  Not statistically significant")
            conclusion.append("")

        return "\n".join(conclusion)

    def stop(self) -> Optional[Exception]:
        """Stop the test and save final results"""
        with self._lock:
            self._running = False

        if self._config.enable_logging:
            try:
                self.save_results()
            except Exception as e:
                print(f"[AB] Failed to save final results: {e}")
                return e

        conclusion = self.get_conclusion()
        print("\n[AB] Test completed")
        print(conclusion)

        return None

    def save_results(self) -> Exception | None:
        """Save current results to JSON file"""
        with self._lock:
            return self._save_results_locked()

    def _save_results_locked(self) -> Exception | None:
        """Save results (locked version)"""
        if not self._config.result_dir:
            return None

        # Prepare data to save
        data: Dict[str, Any] = {
            "config": self._config,
            "results": self._results,
            "statistics": self.calculate_statistics(),
            "conclusion": self.get_conclusion(),
            "start_time": self._start_time,
            "last_updated": time.time(),
        }

        filename = os.path.join(self._config.result_dir, f"{self._config.test_name}.json")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=lambda o: o.__dict__)
            print(f"[AB] Results saved to {filename}")
            return None
        except Exception as e:
            return Exception(f"failed to save results: {e}")

    def _get_variant(self, name: str) -> Optional[ABTestVariant]:
        """Get variant by name"""
        for v in self._variants:
            if v.name == name:
                return v
        return None

    def _compare_variant(self, control: ABTestResult, variant: ABTestResult) -> VariantComparison:
        """Compare variant against control using Welch's t-test"""
        # Compare average PnL per trade
        ctrl_avg = control.total_pnl / control.total_trades if control.total_trades > 0 else 0
        var_avg = variant.total_pnl / variant.total_trades if variant.total_trades > 0 else 0
        diff = var_avg - ctrl_avg

        # Calculate sample variance (approximation)
        ctrl_var = self._estimate_variance(control.total_pnl, control.total_trades)
        var_var = self._estimate_variance(variant.total_pnl, variant.total_trades)

        # Welch's t-test degrees of freedom
        dof = self._degrees_of_freedom(
            ctrl_var / control.total_trades if control.total_trades > 0 else 0,
            var_var / variant.total_trades if variant.total_trades > 0 else 0
        )

        # t-statistic
        denominator = math.sqrt(
            (ctrl_var / control.total_trades if control.total_trades > 0 else 0) +
            (var_var / variant.total_trades if variant.total_trades > 0 else 0)
        )
        if denominator == 0:
            t_stat = 0.0
        else:
            t_stat = diff / denominator

        # Approximate p-value
        p_val = self._two_tail_pvalue(t_stat, dof)

        significant = p_val < self._config.significance_level
        is_better = diff > 0 and significant

        # Calculate Sharpe (simplified)
        ctrl_sharpe = 0.0
        if control.total_trades > 0 and ctrl_var > 0:
            ctrl_sharpe = ctrl_avg / math.sqrt(ctrl_var / control.total_trades)

        var_sharpe = 0.0
        if variant.total_trades > 0 and var_var > 0:
            var_sharpe = var_avg / math.sqrt(var_var / variant.total_trades)

        return VariantComparison(
            variant_name=variant.variant_name,
            control_pnl=control.total_pnl,
            variant_pnl=variant.total_pnl,
            diff_pnl=diff,
            diff_pnl_bps=variant.cumulative_alpha_bps - control.cumulative_alpha_bps,
            control_sharpe=ctrl_sharpe,
            variant_sharpe=var_sharpe,
            diff_sharpe=var_sharpe - ctrl_sharpe,
            p_value=p_val,
            significant=significant,
            is_better=is_better
        )

    @staticmethod
    def _estimate_variance(total: float, n: int) -> float:
        """Estimate variance from total sum (approximation)"""
        if n <= 1:
            return 0.0
        # Very rough approximation when we don't have individual observations
        return (total * total) / float(n * n) * 0.5

    @staticmethod
    def _degrees_of_freedom(v1: float, v2: float) -> float:
        """Welch-Satterthwaite degrees of freedom"""
        if v1 + v2 == 0:
            return 1.0
        num = (v1 + v2) * (v1 + v2)
        den = v1 * v1 + v2 * v2
        if den == 0:
            return 1.0
        return num / den

    @staticmethod
    def _two_tail_pvalue(t: float, dof: float) -> float:
        """Approximate two-tailed p-value from t-statistic"""
        z = abs(t)
        # Normal approximation for large dof
        if dof > 30:
            p = 0.5 * math.erfc(z / math.sqrt(2))
            return 2 * p

        # Simplified approximation for small dof
        p = 0.5 * math.erfc(z / (math.sqrt(1 + dof/10) * math.sqrt(2)))
        return 2 * p
