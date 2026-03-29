# Notebooks - 研究 Notebook

## 说明

本目录包含 Alpha 因子研究和 RL 交易研究的 Notebook 和演示脚本。

## 文件

| 文件 | 说明 |
|------|------|
| `utils.py` | 数据加载和因子计算辅助函数（支持真实币安数据） |
| `rl_utils.py` | RL 研究工具函数（支持真实币安数据、分析、可视化） |
| `demo_factor_research.py` | 纯 Python 版本的因子研究演示 |
| `demo_rl_research.py` | 纯 Python 版本的 RL 研究演示 |

## 快速开始

### 使用真实币安数据

演示脚本会自动从 `data/` 目录加载真实币安 CSV 数据。如果没有找到数据，会自动回退到模拟数据。

**数据文件格式**：
- 文件名格式：`{SYMBOL}-{INTERVAL}-{DATE}.csv`
- 例如：`BTCUSDT-1h-2026-03-10.csv`
- 列：`openTime, open, high, low, close, volume, ...`

项目已包含以下真实数据文件：
- BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
- 时间周期：1m, 5m, 15m, 1h, 4h, 1d
- 日期：2026-03-09 ~ 2026-03-10

### 运行因子研究演示

```bash
cd notebooks
python demo_factor_research.py
```

### 运行 RL 研究演示

```bash
cd notebooks
python demo_rl_research.py
```

### 数据库配置（可选）

如果需要从 PostgreSQL 加载数据，确保 `.env` 文件配置正确：

```bash
# 复制环境变量模板
cp ../.env.example ../.env

# 编辑 .env 配置数据库连接
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=binance
# DB_USER=postgres
# DB_PASSWORD=your_password_here
```

**注意**: RL 演示需要 PyTorch。安装方式（推荐 CPU 版本）：
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### （可选）创建 Jupyter Notebook

如果你有 Jupyter，可以基于演示脚本创建交互式 Notebook。

### 在代码中直接使用真实数据

```python
from notebooks.utils import load_binance_data

# 从 CSV 加载 BTCUSDT 1小时数据
df = load_binance_data(
    symbol='BTCUSDT',
    interval='1h',
    use_database=False  # 设置为 True 使用 PostgreSQL 数据库
)

# 也可以从数据库加载（需要配置数据库连接）
# df = load_binance_data('BTCUSDT', '1h', use_database=True)
```

## 因子列表

### 动量因子 (8个)
- mom_20, mom_60: 20/60日动量
- ema_trend: EMA 趋势
- macd: MACD 动量
- multi_mom: 多周期动量
- mom_accel: 动量加速度
- gap_mom: 跳空动量
- intraday_mom: 日内动量

### 均值回归因子 (7个)
- zscore_20: 20日 Z-score
- bb_pos: 布林带位置
- str_rev: 短期反转
- rsi_rev: RSI 反转
- ma_conv: MA 收敛
- price_pctl: 价格百分位
- channel_rev: 通道突破反转

### 波动率因子 (8个)
- vol_20: 20日已实现波动率
- atr_norm: 归一化 ATR
- vol_breakout: 波动率突破
- vol_change: 波动率变化
- vol_term: 波动率期限结构
- iv_premium: IV 溢价
- vol_corr: 波动率相关性
- jump_vol: 跳升波动率

### 成交量因子 (7个)
- vol_anomaly: 成交量异常
- vol_mom: 成交量动量
- pvt: 价量趋势
- vol_ratio: 成交量比率
- vol_pos: 成交量位置
- vol_conc: 成交量集中度
- vol_div: 量价背离

## 评估指标

### 因子评估
- **IC (Information Coefficient)**: 因子与未来收益的相关性
- **IR (Information Ratio)**: IC 均值 / IC 标准差
- **分层回测**: 按因子分组的多空收益

### RL 评估
- **Total Reward**: 训练总奖励
- **Portfolio Return**: 组合收益率
- **Sharpe Ratio**: 夏普比率
- **Max Drawdown**: 最大回撤
- **Win Rate**: 胜率

---

## RL 工具函数 (`rl_utils.py`)

### 数据准备
- `generate_trading_data()` - 生成真实风格的交易数据（趋势、均值回归、波动聚集）
- `create_env_config()` - 按风格创建环境配置（default/conservative/aggressive/high_freq）
- `get_agent_config()` - 按类型和风格获取智能体配置

### 分析函数
- `analyze_training_history()` - 分析训练历史并计算关键指标
- `compare_agents()` - 对比多个智能体的表现
- `calculate_performance_metrics()` - 计算综合性能指标（收益率、夏普比率、最大回撤等）
- `extract_portfolio_history()` - 提取组合历史
- `print_analysis_summary()` - 打印可读格式的分析摘要
