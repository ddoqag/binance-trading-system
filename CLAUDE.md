```
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
```

## 项目概述

这是一个**币安量化交易系统**，采用 Node.js + Python 双语言架构，已重构为高度可扩展的插件化架构：
- **Node.js**：数据获取（币安 API）、数据库操作
- **Python**：策略回测、机器学习、数据分析、强化学习
- **插件化架构**：所有业务模块（策略、因子、数据源、执行器、风险控制、强化学习等）均为独立插件

## 架构设计文档

项目包含完整的量化交易系统架构设计文档：

| 文档 | 说明 |
|------|------|
| `QUANT_SYSTEM_ARCHITECTURE.md` | 从散户稳定赚钱系统到职业级交易系统的完整架构设计指南 |
| `ARCHITECTURE.md` | 系统核心模块架构设计 |
| `docs/30-终极量化系统架构.md` | 终极量化系统完整蓝图（8个技术层） |
| `docs/18-机构级系统技术栈.md` | 机构级系统技术栈（Go + Python + Kafka + ClickHouse） |
| `docs/29-实时风险控制系统.md` | 实时风险控制系统设计（4层风险控制） |
| `docs/31-从0到1开发路线图.md` | 个人量化系统1年开发路线图 |

主要架构演进路线：散户 MVP → 职业级系统 → 机构级架构

## 常用命令

### Node.js 命令
```bash
npm install              # 安装 Node.js 依赖
npm run docs             # 下载 Binance SDK 文档
npm run fetch            # 获取市场数据（保存 JSON/CSV）
npm run fetch-db         # 获取市场数据并保存到 PostgreSQL
npm run init-db          # 初始化数据库表结构
npm run migrate-db       # 迁移指标数据表
npm run indicators       # 计算技术指标
npm start                # 运行主程序
npm test                 # 运行 Playwright 测试
npm run test:ui          # 运行测试（带 UI）
npm run test:headed      # 运行测试（浏览器可见）
npm run test:debug       # 调试测试
```

### Python 命令
```bash
pip install -r requirements.txt                              # 安装 Python 依赖
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu  # 安装 PyTorch（CPU 版本，用于 RL）

python demo_standalone.py                                    # 独立演示（无外部依赖）
python main_trading_system.py                                # 完整交易系统（带回测）
python strategy_simple_backtest.py                           # 简单回测
python strategy_end_to_end.py                                # 端到端策略回测
python strategy_backtest_fixed.py                            # 固定策略回测
python verify_structure.py                                   # 验证项目结构
python test_modules.py                                       # 运行模块测试
python testnet_demo.py                                       # 币安测试网演示
python notebooks/demo_factor_research.py                     # 因子研究演示
python notebooks/demo_rl_research.py                         # RL 研究演示（需要 PyTorch）
python demo_ai_trading.py                                     # AI驱动的交易系统演示（规则版）
python demo_leverage_trading.py                               # 杠杆交易执行器演示（做多/做空/全仓杠杆）

pytest tests/ -v                                              # 运行所有 Python 测试
pytest tests/test_position.py -v                              # 运行特定测试文件
pytest tests/ --cov                                           # 运行测试并生成覆盖率报告
pytest tests/ -k "test_position"                              # 运行匹配模式的测试
```

## 项目架构

### 核心模块

| 模块 | 目录 | 职责 |
|------|------|------|
| **trading** | `trading/` | 订单管理、交易执行（模拟/实盘、杠杆交易） |
| **strategy** | `strategy/` | 策略基类、双均线/RSI/ML 策略 |
| **risk** | `risk/` | 仓位控制、止损止盈、风险熔断 |
| **models** | `models/` | 特征工程、模型训练、价格预测（包含 30+ Alpha 因子） |
| **rl** | `rl/` | 强化学习交易系统（DQN/PPO 智能体） |
| **ai_trading** | `ai_trading/` | AI驱动的交易系统（市场分析、策略匹配、自动执行） |
| **utils** | `utils/` | 日志、数据库连接、工具函数 |
| **web** | `web/` | Web API 和 UI（预留） |
| **plugins** | `plugins/` | 插件系统核心框架 |
| **plugin_examples** | `plugin_examples/` | 插件示例（Alpha因子、策略、RL智能体等） |

### 插件化架构核心组件

```
┌───────────────────────────────────────────────────────────────────────┐
│                      插件化架构核心层                               │
├───────────────────────────────────────────────────────────────────────┤
│  PluginManager (插件管理器) - 发现、加载、启动、停止插件             │
│  PluginVersionManager (版本管理器) - 语义化版本管理、兼容性检查       │
│  RolloutManager (灰度上线管理器) - 多种上线策略、流量分配、回滚       │
│  ReliableEventBus (可靠事件总线) - 事件序列号、确认、重试、死信队列   │
└───────────────────────────────────────────────────────────────────────┘
                                   ↓
┌───────────────────────────────────────────────────────────────────────┐
│                      插件实例层                                       │
├───────────────────────────────────────────────────────────────────────┤
│  AlphaFactor Plugin (因子插件) - 30+个Alpha因子                        │
│  DualMAStrategy Plugin (策略插件) - 双均线策略                         │
│  DQNAgent Plugin (RL插件) - 深度Q网络智能体                           │
│  PPOAgent Plugin (RL插件) - 近端策略优化智能体                         │
│  BinanceDataSource Plugin (数据源插件) - 币安API数据获取                │
│  RiskManager Plugin (风控插件) - 风险管理和控制                         │
│  SimulatedExecutor Plugin (执行插件) - 模拟交易执行                     │
└───────────────────────────────────────────────────────────────────────┘
```

### 数据流程

```
币安 API → fetch-market-data.js → PostgreSQL/JSON/CSV
    ↓
data_cleaning.py → 清洗后的数据
    ↓
data/loader.py (统一数据加载)
    ↓
┌──────────────────────────────────────────────────────┐
│  特征工程 (models/features.py - 30+ Alpha 因子)        │
│  因子计算 (factors/ - 动量/均值回归/波动率/成交量)       │
│  策略生成 (strategy/)                                 │
│  风险检查 (risk/)                                     │
│  交易执行 (trading/)                                  │
│  强化学习训练 (rl/trainer.py - DQN/PPO)               │
└──────────────────────────────────────────────────────┘
    ↓
Web API (web/api.py - 可选)
```

### 关键文件

| 文件 | 说明 |
|------|------|
| `main_trading_system.py` | Python 主程序入口，回测引擎 |
| `main.js` | Node.js 主入口 |
| `strategy/base.py` | 策略基类，定义 `generate_signals()` 接口 |
| `risk/manager.py` | 综合风险管理器 |
| `models/features.py` | Alpha 因子生成（30+ 因子） |
| `models/model_trainer.py` | ML 模型训练器 |
| `rl/agents/dqn.py` | DQN（深度 Q 网络）智能体实现 |
| `rl/agents/ppo.py` | PPO（近端策略优化）智能体实现 |
| `rl/environment.py` | RL 交易环境 |
| `rl/trainer.py` | RL 训练器 |
| `database.js` | Node.js 数据库操作 |
| `fetch-market-data.js` | 币安数据获取 |
| `plugins/base.py` | 插件基类 |
| `plugins/manager.py` | 插件管理器 |
| `plugins/reliable_event_bus.py` | 可靠事件总线 |
| `plugins/rollout_manager.py` | 灰度上线管理器 |
| `plugin_examples/alpha_factor_plugin.py` | Alpha因子插件示例 |
| `plugin_examples/dual_ma_strategy.py` | 双均线策略插件示例 |
| `plugin_examples/dqn_agent_plugin.py` | DQN智能体插件示例 |
| `notebooks/demo_factor_research.py` | 因子研究演示 |
| `notebooks/demo_rl_research.py` | RL 研究演示 |
| `trading/leverage_executor.py` | 杠杆交易执行器（支持全仓杠杆、做多/做空） |
| `demo_leverage_trading.py` | 杠杆交易执行器演示 |
| `.env.example` | 环境变量模板 |

## 数据库配置

```javascript
{
  host: 'localhost',
  port: 5432,
  database: 'binance',
  user: 'postgres',
  password: '362232'
}
```

### 数据库表

| 表名 | 说明 |
|------|------|
| klines | K 线（蜡烛图）数据 |
| ticker_24hr | 24 小时市场行情 |
| order_book | 订单簿数据 |
| technical_indicators | 技术指标 |

## 交易对和时间周期

- **交易对**: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
- **时间周期**: 1m, 5m, 15m, 1h, 4h, 1d

## 风险参数

- 单笔仓位限制: 20%
- 总仓位限制: 80%
- 每日亏损限制: 5%
- 佣金率: 0.1%（默认）
- 支持止损止盈逻辑
- 支持模拟交易（默认开启）

## Alpha 因子（30+ 个因子）

### 动量因子 (8 个)
- mom_20, mom_60: 20/60 日动量
- ema_trend: EMA 趋势
- macd: MACD 动量
- multi_mom: 多周期动量
- mom_accel: 动量加速度
- gap_mom: 跳空动量
- intraday_mom: 日内动量

### 均值回归因子 (7 个)
- zscore_20: 20 日 Z-score
- bb_pos: 布林带位置
- str_rev: 短期反转
- rsi_rev: RSI 反转
- ma_conv: MA 收敛
- price_pctl: 价格百分位
- channel_rev: 通道突破反转

### 波动率因子 (8 个)
- vol_20: 20 日实现波动率
- atr_norm: 归一化 ATR
- vol_breakout: 波动率突破
- vol_change: 波动率变化
- vol_term: 波动率期限结构
- iv_premium: IV 溢价
- vol_corr: 波动率相关性
- jump_vol: 跳跃波动率

### 成交量因子 (7 个)
- vol_anomaly: 成交量异常
- vol_mom: 成交量动量
- pvt: 价格成交量趋势
- vol_ratio: 成交量比率
- vol_pos: 成交量位置
- vol_conc: 成交量集中度
- vol_div: 成交量背离

## 强化学习

项目包含完整的 RL 交易系统：

### RL 智能体
- **DQN**: 深度 Q 网络，带有经验回放
- **PPO**: 近端策略优化，带有截断目标

### 训练特性
- 层归一化（用于稳定性）
- 状态预处理（NaN/Inf 处理）
- 多环境配置（默认、保守、激进、高频）

### 运行 RL 演示
```bash
# 先安装 PyTorch（CPU 版本）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 运行 RL 研究演示
python notebooks/demo_rl_research.py
```

## 插件系统使用

### 基本使用流程
```python
# 1. 创建事件总线
from plugins.reliable_event_bus import ReliableEventBus
event_bus = ReliableEventBus(name="TradingSystem")
event_bus.start()

# 2. 创建插件管理器
from plugins.manager import PluginManager
plugin_manager = PluginManager(event_bus=event_bus)

# 3. 发现和加载插件
discovered = plugin_manager.discover_plugins()
print(f"发现 {len(discovered)} 个插件")

# 4. 加载插件
plugin_manager.load_plugin("binance_data_source")
plugin_manager.load_plugin("alpha_factor_plugin")
plugin_manager.load_plugin("dual_ma_strategy")

# 5. 启动插件
plugin_manager.start_all_plugins()

# 6. 使用插件
data_source = plugin_manager.get_plugin("binance_data_source")
df = data_source.get_data()

# 7. 健康检查
for name, plugin in plugin_manager.get_all_plugins().items():
    health = plugin.health_check()
    print(f"{name}: {'健康' if health.healthy else '不健康'}")

# 8. 停止和卸载
plugin_manager.stop_all_plugins()
plugin_manager.unload_all_plugins()
event_bus.stop()
```

### 灰度发布流程
```python
# 1. 创建灰度上线管理器
from plugins.rollout_manager import RolloutManager, RolloutStrategy
rollout_manager = RolloutManager()

# 2. 注册新版本
rollout_manager.register_version("alpha_factor_plugin", "1.0.0")
rollout_manager.register_version("alpha_factor_plugin", "2.0.0")

# 3. 创建金丝雀发布计划
canary_plan = rollout_manager.create_canary_rollout(
    plugin_name="alpha_factor_plugin",
    new_version="2.0.0",
    user_percentage=5,  # 5%的用户使用新版本
    duration=3600        # 1小时
)

# 4. 开始发布
rollout_manager.start_rollout(canary_plan.name)

# 5. 逐步增加流量
for percentage in [10, 25, 50, 75, 100]:
    rollout_manager.update_traffic_split(canary_plan.name, percentage)

    # 检查健康状态
    is_healthy = rollout_manager.check_health(canary_plan.name)
    if not is_healthy:
        rollout_manager.rollback_rollout(canary_plan.name)
        break

# 6. 完成发布
rollout_manager.complete_rollout(canary_plan.name)
```

## AI驱动的交易系统架构

项目现在包含完整的AI驱动的量化交易系统架构，具备以下核心组件：

### 架构图
```
Market Data (Binance API)
     ↓
Data Acquisition (Node.js)
     ↓
Storage (PostgreSQL/JSON/CSV)
     ↓
┌───────────────────────────────────────────────┐
│ AI 驱动的交易系统 (Python)                    │
├───────────────────────────────────────────────┤
│ 1. 市场分析器 (MarketAnalyzer)                │
│    - 趋势识别: 上涨/下跌/震荡/高波动            │
│    - 市场状态: 牛市/熊市/中性/高波动            │
│    - 置信度计算: 0.0-1.0                       │
│    - AI增强分析: 使用Qwen3-8B模型              │
│                                               │
│ 2. 策略匹配器 (StrategyMatcher)               │
│    - 策略库管理                               │
│    - 智能匹配: 根据市场状态匹配最佳策略         │
│    - 策略评分: 综合考虑趋势、状态、置信度       │
│    - 切换逻辑: 动态策略调整                     │
│                                               │
│ 3. 交易系统 (AITradingSystem)                 │
│    - 全周期执行: 分析→匹配→生成信号→执行        │
│    - 风险控制: 集成风险管理器                   │
│    - 回测功能: 历史数据回测                     │
│    - 实盘支持: 模拟/实盘切换                     │
└───────────────────────────────────────────────┘
     ↓
Execution Engine (Node.js/Python)
     ↓
Performance Analysis & Reporting
```

### 核心组件

#### MarketAnalyzer (市场分析器)
- **文件**: `ai_trading/market_analyzer.py`
- **功能**:
  - 基于规则的趋势识别
  - AI增强的市场分析（使用Qwen3-8B模型）
  - 支撑/阻力位计算
  - 波动率分析
  - 适合策略推荐

#### StrategyMatcher (策略匹配器)
- **文件**: `ai_trading/strategy_matcher.py`
- **功能**:
  - 策略注册与管理
  - 智能策略匹配
  - 策略优先级排序
  - 历史表现统计
  - 动态策略切换

#### AITradingSystem (AI交易系统)
- **文件**: `ai_trading/ai_trading_system.py`
- **功能**:
  - 完整交易周期执行
  - 集成市场分析和策略匹配
  - 风险管理与控制
  - 回测引擎
  - 模拟交易支持

### 系统特性

#### 1. 智能趋势分析
- 自动识别市场趋势（上涨/下跌/震荡/高波动）
- 计算趋势置信度（0.0-1.0）
- 预测市场状态（牛市/熊市/中性）
- 支撑/阻力位计算

#### 2. 动态策略匹配
- 基于市场状态匹配最佳策略
- 策略优先级管理
- 置信度驱动的策略选择
- 历史表现加权评分

#### 3. 完整交易周期
- 市场数据获取
- 趋势分析
- 策略匹配
- 信号生成
- 风险检查
- 交易执行

#### 4. 多模式支持
- **规则版**: 轻量级，快速执行
- **AI增强版**: 使用Qwen3-8B模型，更精准分析
- **回测模式**: 历史数据测试
- **实盘模式**: 真实交易执行

### 使用方法

#### 快速演示
```bash
# 运行AI交易系统演示（规则版）
python demo_ai_trading.py
```

#### 核心API使用
```python
from ai_trading.ai_trading_system import AITradingSystem

# 初始化系统
config = {
    'symbol': 'BTCUSDT',
    'interval': '1h',
    'initial_capital': 10000,
    'max_position_size': 0.8,
    'paper_trading': True
}
system = AITradingSystem(config)

# 运行完整交易周期
cycle_result = system.execute_trading_cycle()

# 或者运行回测
df = system.load_market_data(lookback=200)
backtest_results = system.run_backtest(df)
```

### 配置选项

#### 核心配置
```python
{
    'symbol': 'BTCUSDT',              # 交易对
    'interval': '1h',                 # 时间周期
    'initial_capital': 10000,         # 初始资金
    'max_position_size': 0.8,         # 总仓位限制
    'max_single_position': 0.2,       # 单笔仓位限制
    'paper_trading': True,           # 模拟交易模式
    'commission_rate': 0.001,        # 佣金率
    'model_path': 'D:/binance/models/Qwen/Qwen3-8B'  # 模型路径
}
```

### 策略库

| 策略 | 类型 | 适合市场 | 描述 |
|------|------|----------|------|
| dual_ma | 趋势跟踪 | 上涨/下跌 | 双均线策略，适合明确趋势 |
| rsi | 均值回归 | 震荡/高波动 | RSI策略，适合震荡市场 |
| dual_ma_conservative | 趋势跟踪 | 上涨/下跌 | 保守版双均线，信号更可靠 |
| rsi_conservative | 均值回归 | 震荡/高波动 | 保守版RSI，减少假信号 |

### 使用场景

#### 场景1：自动策略选择
```python
# 在上涨趋势中会自动选择双均线策略
# 在下跌趋势中会自动选择趋势跟踪策略
# 在震荡市场中会自动选择RSI策略
# 在高波动市场中会自动选择风险控制策略
```

#### 场景2：置信度驱动的决策
```python
# 当趋势置信度高（>0.8）时使用高风险策略
# 当置信度中等（0.6-0.8）时使用平衡策略
# 当置信度低（<0.6）时使用保守策略
```

### 扩展能力

#### 1. 添加新策略
```python
from ai_trading.strategy_matcher import StrategyConfig

# 创建策略配置
new_strategy = StrategyConfig(
    name="my_strategy",
    strategy_class=MyStrategy,
    params={"param1": 10, "param2": 30},
    suitable_trends=[TrendType.UPTREND, TrendType.DOWNTREND],
    suitable_regimes=[MarketRegime.BULL, MarketRegime.BEAR],
    priority=StrategyPriority.PRIMARY,
    description="我的自定义策略"
)

# 注册到策略匹配器
matcher = StrategyMatcher()
matcher.register_strategy(new_strategy)
```

#### 2. 自定义模型
```python
from ai_trading.market_analyzer import MarketAnalyzer

analyzer = MarketAnalyzer(
    model_path="path/to/my/model"
)
```

## 运行测试

### Python 测试 (pytest)
```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_position.py -v

# 运行测试并生成覆盖率报告
pytest tests/ --cov

# 运行匹配模式的测试
pytest tests/ -k "test_position"
```

### 插件系统测试
```bash
pytest test_plugin_system.py -v              # 插件系统端到端测试
pytest test_phase_2.py -v                    # 可靠性增强测试
pytest test_plugin_compatibility.py -v       # 兼容性验证框架测试
pytest test_alpha_factor_plugin.py -v        # Alpha因子插件测试
pytest test_strategy_plugins.py -v           # 策略插件测试
pytest test_rollout_manager.py -v            # 灰度上线机制测试
```

### 测试文件

| 文件 | 说明 |
|------|------|
| `tests/test_helpers.py` | 工具函数测试 |
| `tests/test_position.py` | 仓位管理测试 |
| `tests/test_risk_manager.py` | 风险管理器测试 |
| `tests/test_strategy_base.py` | 策略基类测试 |
| `tests/test_trading_executor.py` | 交易执行器测试 |
| `tests/test_config.py` | 配置测试 |
| `tests/test_indicators.py` | 指标测试 |
| `tests/test_models_features.py` | 特征工程测试 |
| `tests/test_rl_dqn.py` | DQN 智能体测试 |
| `tests/test_rl_ppo.py` | PPO 智能体测试 |
| `tests/test_rl_training.py` | RL 训练测试 |
| `tests/test_rl_environment.py` | RL 环境测试 |
| `tests/integration/test_trading_system.py` | 交易系统集成测试 |

## 环境变量

复制 `.env.example` 到 `.env` 并配置以下变量：

### 数据库配置
| 变量 | 默认值 | 说明 |
|------|--------|------|
| DB_HOST | localhost | 数据库主机 |
| DB_PORT | 5432 | 数据库端口 |
| DB_NAME | binance | 数据库名称 |
| DB_USER | postgres | 数据库用户 |
| DB_PASSWORD | - | 数据库密码 |

### 交易配置
| 变量 | 默认值 | 说明 |
|------|--------|------|
| INITIAL_CAPITAL | 10000 | 初始资金 |
| MAX_POSITION_SIZE | 0.3 | 最大总仓位 (30%) |
| MAX_SINGLE_POSITION | 0.2 | 单笔最大仓位 (20%) |
| PAPER_TRADING | true | 模拟交易模式 |
| COMMISSION_RATE | 0.001 | 佣金率 (0.1%) |
| DEFAULT_SYMBOL | BTCUSDT | 默认交易对 |
| DEFAULT_INTERVAL | 1h | 默认时间周期 |

### 币安 API（可选）
| 变量 | 默认值 | 说明 |
|------|--------|------|
| BINANCE_API_KEY | - | Binance API 密钥 |
| BINANCE_API_SECRET | - | Binance API 密钥密码 |

## 代码规范

- 代码用英文编写，注释和回复用中文
- Python 遵循 PEP 8 规范
- Node.js 遵循 CommonJS 规范
- 插件开发遵循 `plugins/base.py` 定义的接口

## 注意事项

1. **ML 回测**: 使用时间序列分割，避免数据泄露
2. **风险参数**: 默认单笔仓位 20%，总仓位 80%，日亏损限制 5%
3. **模拟交易**: 默认开启，支持滑点和手续费设置
4. **RL 依赖**: 运行强化学习功能需要安装 PyTorch（CPU 或 GPU 版本）
5. **插件开发**: 所有插件需继承 `PluginBase` 基类，实现生命周期方法
