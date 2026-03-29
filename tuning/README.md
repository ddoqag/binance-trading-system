# Tuning - 自动调参模块

基于 Optuna 的贝叶斯优化框架，自动寻找最优策略参数组合。支持单目标、多目标优化和定时自动优化。

## 功能特性

- **贝叶斯优化**：使用 TPE（Tree-structured Parzen Estimator）高效搜索参数空间
- **单目标优化**：最大化夏普比率等单一指标
- **多目标优化**：同时优化多个目标（如夏普 + 回撤）
- **参数空间定义**：支持整数、浮点、类别型参数
- **进度回调**：实时监控优化进度
- **结果持久化**：保存/加载优化结果
- **定时优化**：支持每日自动优化

## 安装依赖

```bash
pip install optuna pandas numpy
```

## 模块结构

```
tuning/
├── __init__.py
└── optimizer.py    # 优化器实现
```

## 核心 API

### 参数空间 (ParameterSpace)

```python
from tuning import ParameterSpace

# 整数参数
fast_ma = ParameterSpace("fast_ma", "int", low=5, high=50)

# 浮点参数（对数尺度）
learning_rate = ParameterSpace("lr", "float", low=1e-5, high=1e-2, log_scale=True)

# 类别参数
strategy_type = ParameterSpace("type", "categorical", choices=["trend", "mean_reversion"])
```

### 优化配置 (OptimizationConfig)

```python
from tuning import OptimizationConfig

config = OptimizationConfig(
    n_trials=100,           # 迭代次数
    timeout=3600,           # 超时时间（秒），可选
    n_jobs=4,               # 并行任务数
    direction="maximize",   # 优化方向: maximize/minimize
    metric="sharpe_ratio",  # 目标指标
    study_name=None,        # Study 名称，默认自动生成
    storage=None,           # Optuna storage URL，可选
)
```

### 策略优化器 (StrategyOptimizer)

#### 基础用法

```python
from tuning import StrategyOptimizer, ParameterSpace, OptimizationConfig
from strategy.dual_ma import DualMAStrategy

# 定义参数空间
param_space = [
    ParameterSpace("fast_ma", "int", 5, 50),
    ParameterSpace("slow_ma", "int", 20, 200),
    ParameterSpace("max_position", "float", 0.1, 0.5),
]

# 创建优化器
optimizer = StrategyOptimizer(
    strategy_class=DualMAStrategy,
    data=data,  # 回测数据
    param_space=param_space,
    config=OptimizationConfig(n_trials=50),
)

# 执行优化
result = optimizer.optimize()

print("最优参数:", result["best_params"])
print(f"最佳夏普: {result['best_value']:.4f}")
```

#### 带进度监控

```python
def progress_callback(current, total):
    pct = current / total * 100
    print(f"优化进度: {pct:.1f}% ({current}/{total})")

result = optimizer.optimize(progress_callback=progress_callback)
```

#### 保存和加载

```python
# 保存优化结果
optimizer.save("optimization_results.json")

# 加载并继续优化
optimizer = StrategyOptimizer.load("optimization_results.json")
best_strategy = optimizer.get_best_strategy()
```

### 多目标优化器 (MultiObjectiveOptimizer)

同时优化多个目标（如最大化夏普，最小化回撤）：

```python
from tuning import MultiObjectiveOptimizer

optimizer = MultiObjectiveOptimizer(
    strategy_class=DualMAStrategy,
    data=data,
    param_space=param_space,
)

# 优化两个目标: [maximize sharpe, minimize max_drawdown]
result = optimizer.optimize(
    n_trials=100,
    directions=["maximize", "minimize"],
)

# 查看 Pareto 前沿
for solution in result["pareto_front"]:
    print(f"参数: {solution['params']}")
    print(f"夏普: {solution['values'][0]:.4f}, 回撤: {solution['values'][1]:.4f}")
```

### 便捷函数

#### `quick_optimize()` - 快速优化

一行代码完成优化：

```python
from tuning import quick_optimize

# 快速优化
result = quick_optimize(
    strategy_class=DualMAStrategy,
    data=data,
    param_space={
        "fast_ma": ("int", 5, 50),
        "slow_ma": ("int", 20, 200),
    },
    n_trials=50,
    metric="sharpe_ratio",
)

print("最优参数:", result["best_params"])
```

参数空间语法：
- `("int", low, high)` - 整数参数
- `("float", low, high)` - 浮点参数

#### `schedule_daily_optimization()` - 定时优化

设置每日自动优化（在后台运行）：

```python
from tuning import StrategyOptimizer, schedule_daily_optimization

optimizer = StrategyOptimizer(...)

# 每天早上 3:00 自动优化
schedule_daily_optimization(optimizer, hour=3, minute=0)

# 主程序继续运行...
import time
while True:
    time.sleep(60)
```

## 完整示例

### 示例1: 双均线策略参数优化

```python
import pandas as pd
from tuning import StrategyOptimizer, ParameterSpace, OptimizationConfig
from strategy.dual_ma import DualMAStrategy

# 加载数据
data = {
    "BTCUSDT": pd.read_csv("data/BTCUSDT_1h.csv", index_col="timestamp", parse_dates=True),
}

# 定义参数空间
param_space = [
    # 均线参数
    ParameterSpace("fast_ma", "int", 5, 30),
    ParameterSpace("slow_ma", "int", 20, 100),
    # RSI 参数
    ParameterSpace("rsi_period", "int", 7, 21),
    ParameterSpace("rsi_overbought", "int", 65, 85),
    ParameterSpace("rsi_oversold", "int", 15, 35),
    # 仓位管理
    ParameterSpace("max_position", "float", 0.2, 0.5),
]

# 配置优化
config = OptimizationConfig(
    n_trials=100,          # 100次迭代
    n_jobs=4,              # 4并行
    direction="maximize",
    metric="sharpe_ratio",
)

# 创建优化器
optimizer = StrategyOptimizer(
    strategy_class=DualMAStrategy,
    data=data,
    param_space=param_space,
    config=config,
)

# 执行优化
print("开始优化...")
result = optimizer.optimize()

# 输出结果
print("\n" + "=" * 50)
print("优化完成")
print("=" * 50)
print(f"最优参数:")
for name, value in result["best_params"].items():
    print(f"  {name}: {value}")
print(f"\n最佳夏普比率: {result['best_value']:.4f}")
print(f"总迭代次数: {result['n_trials']}")

# 保存结果
optimizer.save("dual_ma_optimization.json")

# 获取最优策略实例
best_strategy = optimizer.get_best_strategy()
print(f"\n最优策略: {best_strategy}")
```

### 示例2: 多目标优化（夏普 vs 回撤）

```python
from tuning import MultiObjectiveOptimizer, ParameterSpace

# 定义参数空间
param_space = [
    ParameterSpace("lookback", "int", 10, 100),
    ParameterSpace("threshold", "float", 0.01, 0.1),
]

# 创建多目标优化器
optimizer = MultiObjectiveOptimizer(
    strategy_class=MeanReversionStrategy,
    data=data,
    param_space=param_space,
)

# 执行多目标优化
result = optimizer.optimize(
    n_trials=100,
    directions=["maximize", "minimize"],  # max sharpe, min drawdown
)

# 分析 Pareto 前沿
print(f"Pareto 前沿解数量: {result['n_pareto']}")
print("\n所有非支配解:")
for i, solution in enumerate(result["pareto_front"]):
    sharpe = solution["values"][0]
    drawdown = abs(solution["values"][1])
    print(f"  解 {i+1}: 夏普={sharpe:.4f}, 回撤={drawdown:.2%}")
    print(f"    参数: {solution['params']}")
```

### 示例3: 使用 Optuna Storage（持久化）

```python
from tuning import StrategyOptimizer, OptimizationConfig

# 使用数据库存储优化历史
config = OptimizationConfig(
    n_trials=100,
    study_name="dual_ma_study",
    storage="sqlite:///optuna_studies.db",  # SQLite 存储
)

optimizer = StrategyOptimizer(
    strategy_class=DualMAStrategy,
    data=data,
    config=config,
)

# 优化结果自动保存到数据库
result = optimizer.optimize()

# 后续可以继续优化（从上次结果继续）
# 只需使用相同的 study_name 和 storage
```

### 示例4: 自定义优化目标

```python
from tuning import StrategyOptimizer
from backtest import BacktestEngine, BacktestConfig

class CustomOptimizer(StrategyOptimizer):
    def _objective(self, trial):
        """自定义目标函数"""
        # 建议参数
        params = {}
        for p in self.param_space:
            params[p.name] = p.suggest(trial)

        # 创建策略
        strategy = self.strategy_class(**params)

        # 运行回测
        config = BacktestConfig()
        engine = BacktestEngine(config)
        engine.add_strategy(strategy)
        result = engine.run(self.data)

        metrics = result.get("metrics")
        if not metrics:
            return -1e10

        # 自定义目标：夏普 - 0.5 * 回撤
        sharpe = metrics.sharpe_ratio
        drawdown = abs(metrics.max_drawdown)
        custom_score = sharpe - 0.5 * drawdown

        return custom_score
```

## 算法原理

### 贝叶斯优化流程

```
1. 随机采样初始点（Warm-up）
2. 构建代理模型（TPE估计好坏参数区域）
3. 根据采集函数选择下一个评估点
4. 评估目标函数
5. 更新代理模型
6. 重复3-5直到收敛或达到最大迭代
```

### TPE (Tree-structured Parzen Estimator)

- **高斯混合模型**：估计好参数和坏参数的分布
- **期望改进 (EI)**：选择最有希望改进的点
- **自适应**：自动调整探索/利用平衡

优势：
- ✅ 比网格搜索高效（避免指数爆炸）
- ✅ 比随机搜索智能（利用历史信息）
- ✅ 处理条件参数（某些参数依赖其他参数）
- ✅ 支持多目标优化

## 参数调优指南

### 调参策略

| 参数类型 | 建议范围 | 说明 |
|---------|---------|------|
| 均线周期 | 5-200 | 短周期敏感，长周期稳健 |
| 仓位比例 | 0.1-0.5 | 根据风险偏好调整 |
| 阈值类 | 对数尺度 | 如 `1e-3` 到 `1e-1` |
| RSI 阈值 | 60-85（超买）| 15-40（超卖）|

### 避免过拟合

```python
# 1. 使用 Walk-Forward 验证
def objective(trial):
    params = {...}

    # 多次滚动验证
    scores = []
    for train_data, test_data in walk_forward_split(data):
        strategy = create_strategy(params)
        score = backtest(strategy, test_data)
        scores.append(score)

    return np.mean(scores)  # 平均表现

# 2. 限制参数复杂度
param_space = [
    ParameterSpace("ma", "int", 10, 50),  # 避免过大的范围
]

# 3. 使用早停
config = OptimizationConfig(
    n_trials=100,
    timeout=3600,  # 限制总时间
)
```

## 测试

```bash
# 运行调参模块测试
pytest tests/test_optimizer*.py -v

# 覆盖率报告
pytest tests/test_optimizer*.py --cov=tuning --cov-report=html
```

## 性能优化

| 优化项 | 效果 |
|--------|------|
| 并行优化 (n_jobs) | 线性加速（CPU核心数限制） |
| 减少回测数据 | 减少单次评估时间 |
| 早停（timeout） | 避免无效搜索 |
| 剪枝（pruning） | 提前终止无望试验 |

### 启用剪枝

```python
import optuna

def objective(trial):
    # ... 参数建议

    # 分阶段评估，支持中间剪枝
    for step in range(10):
        score = evaluate_partial(params, step)
        trial.report(score, step)

        if trial.should_prune():
            raise optuna.TrialPruned()

    return final_score

# 使用剪枝器
study = optuna.create_study(
    pruner=optuna.pruners.MedianPruner(),
)
```

## 注意事项

1. **随机种子**：结果可能因随机性略有不同，建议多次运行取平均
2. **计算资源**：贝叶斯优化计算量较大，建议在服务器/云端运行
3. **数据泄露**：确保训练集和验证集严格分离
4. **参数相关性**：某些参数组合可能无效，需在策略中检查
5. **过拟合风险**：优化次数越多，过拟合风险越高

## 参考

- [Optuna 官方文档](https://optuna.readthedocs.io/)
- [Algorithms for Hyper-Parameter Optimization (Bergstra et al., 2011)](https://papers.nips.cc/paper/2011/hash/86e8f7ab32cfd12577bc2619bc635690-Abstract.html)
- [Taking the Human Out of the Loop: A Review of Bayesian Optimization (Shahriari et al., 2016)](https://doi.org/10.1109/TKDE.2017.2695454)

## License

MIT License - 参见项目根目录 LICENSE 文件
