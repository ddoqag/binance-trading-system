# Portfolio - 投资组合管理模块

机构级投资组合管理，提供协方差矩阵计算和风险平价资金分配功能。

## 功能特性

- **多方法协方差矩阵**：标准、指数加权移动平均 (EWM)、Ledoit-Wolf 收缩估计
- **风险平价权重**：数值优化实现真实风险平价，各资产风险贡献相等
- **逆波动率权重**：风险平价的快速近似解
- **层次风险平价**：基于相关性的聚类分配（处理相关性过高的情况）

## 安装依赖

```bash
pip install numpy pandas
```

## 模块结构

```
portfolio/
├── __init__.py
├── covariance.py      # 协方差矩阵计算
└── risk_parity.py     # 风险平价权重计算
```

## 核心 API

### 协方差矩阵 (covariance.py)

#### `calculate_returns(prices, method="log")`

计算收益率序列。

```python
import pandas as pd
from portfolio.covariance import calculate_returns

# 价格数据
prices = pd.DataFrame({
    "BTCUSDT": [40000, 41000, 40500, 42000],
    "ETHUSDT": [2000, 2100, 2050, 2200],
})

# 对数收益率
returns = calculate_returns(prices, method="log")

# 简单收益率
simple_returns = calculate_returns(prices, method="simple")
```

#### `calculate_covariance(returns, method="standard", span=60, shrinkage=0.1)`

计算协方差矩阵，支持三种方法：

| 方法 | 描述 | 适用场景 |
|------|------|---------|
| `standard` | 标准样本协方差 | 数据充足、低维度 |
| `ewm` | 指数加权移动平均 | 重视近期数据 |
| `shrinkage` | Ledoit-Wolf 收缩 | 高维度、矩阵病态 |

```python
from portfolio.covariance import calculate_covariance

# 标准协方差
cov_std = calculate_covariance(returns, method="standard")

# EWM 协方差（60周期半衰期）
cov_ewm = calculate_covariance(returns, method="ewm", span=60)

# Ledoit-Wolf 收缩（稳定估计）
cov_lw = calculate_covariance(returns, method="shrinkage", shrinkage=0.1)
```

#### `portfolio_volatility(weights, cov_matrix)`

计算组合波动率。

```python
from portfolio.covariance import portfolio_volatility

weights = np.array([0.5, 0.5])
cov = calculate_covariance(returns)

vol = portfolio_volatility(weights, cov.values)
print(f"组合波动率: {vol:.2%}")
```

### 风险平价 (risk_parity.py)

#### `risk_parity_weights(cov_matrix, max_iter=1000, tol=1e-8)`

计算风险平价权重。使用数值优化使各资产对组合风险的边际贡献相等。

```python
from portfolio.covariance import calculate_covariance
from portfolio.risk_parity import risk_parity_weights

# 多币种收益率
data = {
    "BTCUSDT": df_btc["close"],
    "ETHUSDT": df_eth["close"],
    "SOLUSDT": df_sol["close"],
}
returns = calculate_returns(pd.DataFrame(data))
cov = calculate_covariance(returns)

# 计算风险平价权重
weights = risk_parity_weights(cov.values)

for symbol, w in zip(data.keys(), weights):
    print(f"{symbol}: {w:.2%}")
```

#### `verify_risk_parity(weights, cov_matrix, tol=0.01)`

验证风险平价结果。检查各资产风险贡献是否均衡。

```python
from portfolio.risk_parity import verify_risk_parity

is_valid, rc = verify_risk_parity(weights, cov.values)
print(f"风险贡献: {rc}")
print(f"均衡验证: {'通过' if is_valid else '失败'}")
```

#### `inverse_volatility_weights(cov_matrix)`

逆波动率权重（快速近似解）。

```python
from portfolio.risk_parity import inverse_volatility_weights

# 计算更快，但非精确风险平价
weights = inverse_volatility_weights(cov.values)
```

#### `hierarchical_risk_parity(returns, method="single")`

层次风险平价（HRP）。

```python
from portfolio.risk_parity import hierarchical_risk_parity

# 处理高相关性的聚类方法
weights = hierarchical_risk_parity(returns, method="single")
```

## 完整示例

### 多币种组合配置

```python
import pandas as pd
import numpy as np
from portfolio.covariance import calculate_returns, calculate_covariance
from portfolio.risk_parity import risk_parity_weights, verify_risk_parity

# 1. 加载数据
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
data = {}
for symbol in symbols:
    df = pd.read_csv(f"data/{symbol}_1h.csv", index_col="timestamp", parse_dates=True)
    data[symbol] = df["close"]

# 2. 计算收益率
prices = pd.DataFrame(data)
returns = calculate_returns(prices)

# 3. 计算协方差矩阵（使用收缩估计提高稳定性）
cov_matrix = calculate_covariance(returns, method="shrinkage", shrinkage=0.1)

# 4. 计算风险平价权重
weights = risk_parity_weights(cov_matrix.values)

# 5. 验证结果
is_valid, rc = verify_risk_parity(weights, cov_matrix.values)
print("风险平价权重:")
for symbol, w in zip(symbols, weights):
    print(f"  {symbol}: {w:.2%}")
print(f"\n各资产风险贡献: {rc}")
print(f"风险贡献标准差: {np.std(rc):.4f}")
```

### 回测集成

```python
from backtest import BacktestEngine, BacktestConfig
from portfolio.covariance import calculate_covariance
from portfolio.risk_parity import risk_parity_weights

# 配置：启用风险平价
config = BacktestConfig(
    use_risk_parity=True,
    risk_lookback=60,      # 使用60周期历史计算风险
    rebalance_freq=5,      # 每5周期再平衡
)

engine = BacktestEngine(config)
engine.add_strategy(my_strategy)

# 回测引擎会自动调用风险平价分配
result = engine.run(data)
```

## 算法详解

### 风险平价数学原理

风险平价的核心是让各资产对组合总风险的边际贡献相等：

```
组合风险: σ(w) = √(w'Σw)
风险贡献: RC_i = w_i * (Σw)_i / σ(w)
目标: RC_i = RC_j for all i,j
```

通过最小化风险贡献的方差来求解：
```python
minimize: Σ(RC_i - RC̄)²
subject to: Σw_i = 1, w_i ≥ 0
```

### Ledoit-Wolf 收缩估计

解决样本协方差矩阵在高维度下的不稳定问题：

```
Σ* = δ·F + (1-δ)·S

S: 样本协方差矩阵
F: 目标矩阵（通常用对角阵）
δ: 收缩系数 (0 ≤ δ ≤ 1)
```

## 测试

```bash
# 运行本模块测试
pytest tests/test_portfolio*.py -v

# 覆盖率
pytest tests/test_portfolio*.py --cov=portfolio --cov-report=html
```

## 性能优化

| 方法 | 计算复杂度 | 适用规模 |
|------|-----------|---------|
| 逆波动率 | O(n) | 快速近似，任意规模 |
| 风险平价 | O(n²) | 精确解，<50资产 |
| 层次风险平价 | O(n²) | 高相关性场景 |

## 参考

- [Risk Parity and Budgeting (Roncalli, 2013)](https://www.amazon.com/Risk-Parity-Budgeting-Financial-Risk/dp/1482207155)
- [Ledoit & Wolf (2004) - Honey, I Shrunk the Sample Covariance Matrix](https://doi.org/10.1002/jae.753)
- [Hierarchical Risk Parity (López de Prado, 2016)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)

## 注意事项

1. **数据长度**：协方差矩阵估计至少需要 2n 个样本（n 为资产数量）
2. **矩阵正定性**：确保收益率数据无共线性，必要时使用收缩估计
3. **再平衡成本**：频繁再平衡会产生交易成本，需权衡
4. **极端行情**：风险平价在市场危机时可能失效，需配合风控

## License

MIT License - 参见项目根目录 LICENSE 文件
