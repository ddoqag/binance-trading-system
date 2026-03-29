# 贡献指南
<!-- AUTO-GENERATED -->

## 开发环境设置

### 前置条件

| 工具 | 最低版本 | 用途 |
|------|----------|------|
| Node.js | 18+ | 数据获取、数据库操作 |
| Python | 3.10+ | 策略回测、机器学习、强化学习 |
| PostgreSQL | 14+ | K线/行情数据持久化存储 |
| Redis | 7+ | 实时数据缓存（WSL2 环境推荐） |
| Git | 2.x | 版本控制 |

### 安装步骤

```bash
# 1. 克隆仓库
git clone <repo-url>
cd binance

# 2. 安装 Node.js 依赖
npm install

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装 PyTorch（CPU 版本，用于强化学习）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env，填入数据库密码和 API 密钥

# 6. 初始化数据库
npm run init-db

# 7. 验证项目结构
python verify_structure.py
```

## 可用脚本

参见 [`docs/SCRIPTS.md`](./SCRIPTS.md) 获取完整命令列表。

常用开发命令：

```bash
# Node.js 数据层
npm run fetch-db          # 从币安 API 获取数据并存入数据库
npm run indicators        # 计算技术指标
npm start                 # 启动主程序

# Python 策略层
python demo_standalone.py              # 快速验证环境（无外部依赖）
python main_trading_system.py          # 完整交易系统回测
python demo_ai_trading.py             # AI 驱动交易演示
python demo_leverage_trading.py       # 杠杆交易演示

# trading_system（Phase 1–3）
python -m trading_system.trader                          # 启动 paper trading 循环
python -m training_system.train --db --symbol BTCUSDT \
    --interval 1h --out models/lgbm_btc_1h.txt          # 训练 LightGBM 信号模型
```

## 测试流程

### Python 测试（pytest）

```bash
# 运行所有测试
pytest tests/ -v

# trading_system（Phase 1）
pytest tests/trading_system/ -v

# training_system（Phase 2）
pytest tests/training_system/ -v

# 运行特定模块
pytest tests/test_position.py -v
pytest tests/test_risk_manager.py -v
pytest tests/test_rl_dqn.py -v

# 生成覆盖率报告（目标：80%+）
pytest tests/ --cov --cov-report=html

# 插件系统测试
pytest test_plugin_system.py -v
pytest test_phase_2.py -v
pytest test_rollout_manager.py -v
```

### Node.js 测试（Playwright）

```bash
npm test                  # 无头模式运行
npm run test:ui           # 带 UI 界面
npm run test:headed       # 显示浏览器
npm run test:debug        # 调试模式
```

### 编写新测试

- Python 测试文件放在 `tests/` 目录，命名为 `test_*.py`
- 集成测试放在 `tests/integration/`
- 遵循 TDD 工作流：先写测试（RED）→ 实现（GREEN）→ 重构（IMPROVE）
- 保持 80%+ 覆盖率

## 代码规范

- **语言约定**：代码用英文，注释和提交信息用中文
- **Python**：遵循 PEP 8，使用类型提示
- **Node.js**：遵循 CommonJS 规范
- **插件开发**：继承 `plugins/base.py` 中的 `PluginBase`，实现生命周期方法
- **不可变数据**：创建新对象，不要直接修改原对象
- **函数大小**：单函数不超过 50 行
- **文件大小**：单文件不超过 800 行

## PR 提交清单

提交 PR 前确认以下事项：

- [ ] 代码用英文编写，注释/提交信息用中文
- [ ] 新功能包含对应的测试用例
- [ ] 测试覆盖率不低于 80%
- [ ] 没有硬编码的密钥或密码（使用环境变量）
- [ ] 已在本地运行 `pytest tests/ -v` 并全部通过
- [ ] 遵循 `plugins/base.py` 接口（如涉及插件开发）
- [ ] 提交信息格式：`<type>: <中文描述>`（types: feat/fix/refactor/docs/test/chore）

## 项目结构

```
binance/
├── trading_system/   # Phase 1-3 交易循环（Trader、策略、风控、执行）
│   ├── trader.py         # 主循环（step / run）
│   ├── strategy.py       # AlphaStrategy（规则版）
│   ├── lgbm_model.py     # LGBMStrategy（LightGBM 版）
│   ├── regime_strategy.py# RegimeAwareLGBMStrategy（Regime 感知版）
│   ├── monitor.py        # EquityMonitor（权益曲线 + 回撤警报）
│   ├── risk_manager.py   # ATR 风控 + 三重熔断
│   ├── position.py       # 仓位状态机
│   ├── executor.py       # PaperExecutor（含滑点/手续费仿真）
│   ├── ai_context.py     # AI 浏览器集成（8模型市场分析）
│   └── bandit_allocator.py # EXP3 Bandit 动态策略分配
│
├── training_system/  # Phase 2 LightGBM 训练管线
│   ├── train.py          # 训练入口（--db / --csv）
│   ├── features.py       # 10 个技术特征
│   ├── labels.py         # 阈值过滤标签
│   ├── dataset.py        # 构建 (X, y) 矩阵
│   ├── walkforward.py    # 滚动时间序列分割
│   ├── model.py          # lgb.train 包装
│   ├── objective.py      # Optuna 目标函数（AUC）
│   ├── evaluate.py       # 评估指标
│   └── db_loader.py      # PostgreSQL 数据加载
│
├── portfolio_system/ # Phase 4 组合交易
│   ├── portfolio_trader.py  # 组合交易器（多币种 + 风险平价）
│   └── bandit_allocator.py  # Bandit 策略分配器
│
├── backtest/         # 回测框架
│   ├── engine.py         # 回测引擎（含风险平价）
│   └── metrics.py        # 绩效指标计算
│
├── portfolio/        # 机构级投资组合
│   ├── covariance.py     # 协方差矩阵计算
│   └── risk_parity.py    # 风险平价权重计算
│
├── tuning/           # 自动调参
│   └── optimizer.py      # Optuna 贝叶斯优化
│
├── rl/               # Phase 4 RL 决策融合
│   ├── meta_controller.py  # PPO Meta-Controller（策略权重动态分配）
│   ├── strategy_pool.py    # 策略池管理
│   ├── fusion_trainer.py   # 融合训练器
│   ├── environment.py      # 交易环境
│   ├── trainer.py          # RL 训练器
│   └── agents/             # DQN/PPO 智能体
│
├── strategy/         # Phase 5 高频策略
│   ├── base.py             # 策略基类
│   ├── dual_ma.py          # 双均线策略
│   ├── rsi_strategy.py     # RSI 策略
│   ├── ml_strategy.py      # ML 策略
│   └── orderbook_strategies.py  # 订单簿微观结构策略
│
├── rust_execution/   # Phase 5 Rust 执行引擎
│   ├── src/
│   │   ├── lib.rs          # PyO3 Python 绑定
│   │   ├── engine.rs       # 执行引擎核心
│   │   └── types.rs        # 类型定义
│   └── Cargo.toml
│
├── trading/          # 交易执行
│   ├── leverage_executor.py  # 杠杆交易执行器
│   ├── execution.py          # 基础执行
│   └── rust_execution_bridge.py  # Rust 引擎桥接
│
├── models/           # 机器学习（30+ Alpha 因子）
├── ai_trading/       # AI 驱动交易系统
├── plugins/          # 插件系统核心
├── tests/            # Python 测试套件（114+ 用例）
├── data/             # 市场数据（JSON/CSV）
├── docs/             # 项目文档
└── utils/            # 工具函数
```
