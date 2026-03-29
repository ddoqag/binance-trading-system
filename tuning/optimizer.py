# tuning/optimizer.py
"""
自动调参模块。

基于 Optuna 的贝叶斯优化，自动寻找最优策略参数。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import optuna
from typing import Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
import json
import pickle
from pathlib import Path

from backtest.engine import BacktestEngine, BacktestConfig
from backtest.metrics import calculate_sharpe_ratio


# Optuna 日志级别设置
optuna.logging.set_verbosity(optuna.logging.WARNING)


@dataclass
class ParameterSpace:
    """参数空间定义。"""

    name: str
    param_type: str  # 'int', 'float', 'categorical'
    low: float | None = None
    high: float | None = None
    choices: list[Any] | None = None
    log_scale: bool = False

    def suggest(self, trial: optuna.Trial) -> Any:
        """在Optuna trial中建议参数值。"""
        if self.param_type == 'int':
            return trial.suggest_int(self.name, int(self.low), int(self.high))
        elif self.param_type == 'float':
            return trial.suggest_float(
                self.name, self.low, self.high, log=self.log_scale
            )
        elif self.param_type == 'categorical':
            return trial.suggest_categorical(self.name, self.choices)
        else:
            raise ValueError(f"Unknown param type: {self.param_type}")


@dataclass
class OptimizationConfig:
    """优化配置。"""

    n_trials: int = 100
    timeout: int | None = None  # 秒
    n_jobs: int = 1
    direction: str = "maximize"  # 'maximize' or 'minimize'
    metric: str = "sharpe_ratio"  # 优化目标
    study_name: str | None = None
    storage: str | None = None  # Optuna storage URL


def default_param_space() -> list[ParameterSpace]:
    """默认参数空间。"""
    return [
        # 双均线参数
        ParameterSpace("fast_ma", "int", 5, 50),
        ParameterSpace("slow_ma", "int", 20, 200),
        # RSI参数
        ParameterSpace("rsi_period", "int", 7, 30),
        ParameterSpace("rsi_overbought", "int", 60, 85),
        ParameterSpace("rsi_oversold", "int", 15, 40),
        # 仓位管理
        ParameterSpace("max_position", "float", 0.3, 0.9),
        ParameterSpace("risk_lookback", "int", 20, 100),
        # 再平衡频率
        ParameterSpace("rebalance_freq", "int", 1, 20),
    ]


class StrategyOptimizer:
    """
    策略参数优化器。

    使用贝叶斯优化自动寻找最优参数组合。
    """

    def __init__(
        self,
        strategy_class: type,
        data: dict[str, pd.DataFrame],
        param_space: list[ParameterSpace] | None = None,
        config: OptimizationConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ):
        self.strategy_class = strategy_class
        self.data = data
        self.param_space = param_space or default_param_space()
        self.config = config or OptimizationConfig()
        self.backtest_config = backtest_config or BacktestConfig()

        self.study: optuna.Study | None = None
        self.best_params: dict | None = None
        self.optimization_history: list[dict] = []

    def optimize(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict:
        """
        执行优化。

        Returns:
            最优参数和结果
        """
        # 创建study
        study_name = self.config.study_name or f"optimization_{datetime.now():%Y%m%d_%H%M%S}"

        self.study = optuna.create_study(
            direction=self.config.direction,
            study_name=study_name,
            storage=self.config.storage,
            load_if_exists=True,
        )

        # 运行优化
        self.study.optimize(
            self._objective,
            n_trials=self.config.n_trials,
            timeout=self.config.timeout,
            n_jobs=self.config.n_jobs,
            callbacks=[self._callback(progress_callback)],
            show_progress_bar=False,
        )

        # 保存结果
        self.best_params = self.study.best_params

        return {
            "best_params": self.best_params,
            "best_value": self.study.best_value,
            "n_trials": len(self.study.trials),
            "optimization_history": self.optimization_history,
        }

    def _objective(self, trial: optuna.Trial) -> float:
        """优化目标函数。"""
        # 建议参数
        params = {}
        for p in self.param_space:
            params[p.name] = p.suggest(trial)

        # 创建策略
        strategy = self.strategy_class(**params)

        # 更新回测配置
        config = BacktestConfig(
            **{
                **self.backtest_config.__dict__,
                "max_position": params.get("max_position", self.backtest_config.max_position),
                "rebalance_freq": params.get("rebalance_freq", self.backtest_config.rebalance_freq),
            }
        )

        # 运行回测
        engine = BacktestEngine(config=config)
        engine.add_strategy(strategy)

        try:
            result = engine.run(self.data)

            # 获取优化目标
            metrics = result.get("metrics")
            if not metrics:
                return -1e10

            metric_value = getattr(metrics, self.config.metric, 0)

            # 记录历史
            self.optimization_history.append({
                "params": params,
                "metric": metric_value,
            })

            # 处理无效值
            if np.isnan(metric_value) or np.isinf(metric_value):
                return -1e10

            return metric_value

        except Exception as e:
            trial.set_user_attr("error", str(e))
            return -1e10

    def _callback(
        self, progress_callback: Callable[[int, int], None] | None
    ) -> Callable:
        """创建进度回调。"""
        def callback(study: optuna.Study, trial: optuna.FrozenTrial):
            if progress_callback:
                progress_callback(len(study.trials), self.config.n_trials)
        return callback

    def get_best_strategy(self) -> Any:
        """获取最优参数对应的策略实例。"""
        if not self.best_params:
            raise ValueError("Must run optimize() first")
        return self.strategy_class(**self.best_params)

    def save(self, path: str) -> None:
        """保存优化结果。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        result = {
            "best_params": self.best_params,
            "param_space": [
                {"name": p.name, "type": p.param_type, "low": p.low, "high": p.high}
                for p in self.param_space
            ],
            "config": self.config.__dict__,
            "optimization_history": self.optimization_history,
        }

        with open(path, "w") as f:
            json.dump(result, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "StrategyOptimizer":
        """加载优化结果。"""
        with open(path, "r") as f:
            data = json.load(f)

        # 重建参数空间
        param_space = [
            ParameterSpace(p["name"], p["type"], p.get("low"), p.get("high"))
            for p in data["param_space"]
        ]

        instance = cls.__new__(cls)
        instance.param_space = param_space
        instance.best_params = data["best_params"]
        instance.optimization_history = data["optimization_history"]

        return instance


class MultiObjectiveOptimizer:
    """
    多目标优化器。

    同时优化多个目标（如：最大化夏普 + 最小化回撤）。
    """

    def __init__(
        self,
        strategy_class: type,
        data: dict[str, pd.DataFrame],
        param_space: list[ParameterSpace] | None = None,
        backtest_config: BacktestConfig | None = None,
    ):
        self.strategy_class = strategy_class
        self.data = data
        self.param_space = param_space or default_param_space()
        self.backtest_config = backtest_config or BacktestConfig()

        self.study: optuna.Study | None = None

    def optimize(
        self,
        n_trials: int = 100,
        directions: list[str] = ["maximize", "minimize"],
    ) -> dict:
        """
        执行多目标优化。

        Args:
            n_trials: 迭代次数
            directions: 各目标的优化方向

        Returns:
            Pareto前沿解集
        """
        self.study = optuna.create_study(
            directions=directions,
            study_name=f"multi_objective_{datetime.now():%Y%m%d_%H%M%S}",
        )

        self.study.optimize(
            self._objective,
            n_trials=n_trials,
            show_progress_bar=False,
        )

        # 获取Pareto前沿
        pareto_front = self.study.best_trials

        return {
            "pareto_front": [
                {
                    "params": t.params,
                    "values": t.values,
                }
                for t in pareto_front
            ],
            "n_pareto": len(pareto_front),
        }

    def _objective(self, trial: optuna.Trial) -> tuple[float, float]:
        """多目标函数：返回 (sharpe, -max_drawdown)。"""
        # 建议参数
        params = {p.name: p.suggest(trial) for p in self.param_space}

        # 创建策略和回测
        strategy = self.strategy_class(**params)
        engine = BacktestEngine(config=self.backtest_config)
        engine.add_strategy(strategy)

        try:
            result = engine.run(self.data)
            metrics = result.get("metrics")

            if not metrics:
                return -1e10, 0

            sharpe = metrics.sharpe_ratio
            max_dd = abs(metrics.max_drawdown)

            return sharpe, -max_dd  # 最大化sharpe，最小化max_dd

        except Exception:
            return -1e10, 0


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def quick_optimize(
    strategy_class: type,
    data: dict[str, pd.DataFrame],
    param_space: dict[str, tuple],
    n_trials: int = 50,
    metric: str = "sharpe_ratio",
) -> dict:
    """
    快速优化函数。

    Args:
        strategy_class: 策略类
        data: 回测数据
        param_space: 参数字典，格式：{"param_name": ("int", low, high)}
        n_trials: 迭代次数
        metric: 优化目标

    Returns:
        最优参数

    Example:
        >>> param_space = {
        ...     "fast_ma": ("int", 5, 50),
        ...     "slow_ma": ("int", 20, 200),
        ... }
        >>> result = quick_optimize(MyStrategy, data, param_space, n_trials=50)
    """
    # 转换参数空间
    spaces = []
    for name, spec in param_space.items():
        if spec[0] == "int":
            spaces.append(ParameterSpace(name, "int", spec[1], spec[2]))
        elif spec[0] == "float":
            spaces.append(ParameterSpace(name, "float", spec[1], spec[2]))

    config = OptimizationConfig(n_trials=n_trials, metric=metric)

    optimizer = StrategyOptimizer(
        strategy_class=strategy_class,
        data=data,
        param_space=spaces,
        config=config,
    )

    return optimizer.optimize()


def schedule_daily_optimization(
    optimizer: StrategyOptimizer,
    hour: int = 3,
    minute: int = 0,
) -> None:
    """
    设置每日自动优化。

    使用 schedule 库在每天指定时间运行优化。

    Args:
        optimizer: 优化器实例
        hour: 小时
        minute: 分钟
    """
    import schedule
    import time

    def job():
        print(f"[{datetime.now()}] 开始每日优化...")
        result = optimizer.optimize()
        print(f"优化完成，最佳参数: {result['best_params']}")
        print(f"最佳值: {result['best_value']:.4f}")

    schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(job)

    print(f"已设置每日 {hour:02d}:{minute:02d} 自动优化")

    # 运行调度循环（在新线程中）
    import threading

    def run_schedule():
        while True:
            schedule.run_pending()
            time.sleep(60)

    thread = threading.Thread(target=run_schedule, daemon=True)
    thread.start()

