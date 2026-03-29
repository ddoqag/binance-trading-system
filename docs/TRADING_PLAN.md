# 实盘交易计划

## 1. 项目概述
- 项目名称：币安量化交易系统
- 架构：Node.js + Python 双语言架构，插件化设计
- 核心功能：市场分析、策略匹配、交易执行、风险管理
- 支持：现货、期货、全仓杠杆、做空/做多

## 2. 环境准备

### 2.1 Node.js 环境
```bash
# 安装 Node.js 依赖
npm install

# 验证依赖
npm list
```

### 2.2 Python 环境
```bash
# 安装基础依赖
pip install -r requirements.txt

# 安装 PyTorch（CPU 版本，用于强化学习）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 2.3 数据库配置
```bash
# 初始化数据库表结构
npm run init-db

# 验证数据库连接
node test-db-connection.js
```

### 2.4 Redis 配置
```bash
# 确保 WSL2 中 Redis 已运行
wsl --user root systemctl status redis-server

# 验证 Redis 连接
node test_redis_connection.js

# 运行 Redis 管理器测试
node redis_manager.js

# 运行 Redis 集成示例
node demo_redis_integration.js
```

### 2.5 环境变量配置
复制 `.env.example` 到 `.env` 并配置：
```
# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_NAME=binance
DB_USER=postgres
DB_PASSWORD=362232

# 交易配置
INITIAL_CAPITAL=10000
MAX_POSITION_SIZE=0.8
MAX_SINGLE_POSITION=0.2
PAPER_TRADING=true
COMMISSION_RATE=0.001
DEFAULT_SYMBOL=BTCUSDT
DEFAULT_INTERVAL=1h

# 币安 API（可选）
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# Redis 配置（可选，用于缓存和状态管理）
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

## 3. 系统验证

### 3.1 核心功能测试
```bash
# 运行 REST API 测试
node run_simple_example.js

# 运行 WebSocket 测试（期货）
node test_websocket_fixed.js

# 运行杠杆交易测试（真实数据）
python test_leverage_no_unicode.py
```

### 3.2 Redis 功能验证
```bash
# 验证 Redis 连接
node test_redis_connection.js

# 验证 Redis 管理器功能
node redis_manager.js

# 验证 Redis 集成示例
node demo_redis_integration.js
```

### 3.3 数据库数据验证
```bash
# 验证数据完整性
npm run fetch-db

# 运行数据清洗
python data_cleaning.py
```

### 3.3 策略回测
```bash
# 简单策略回测
python strategy_simple_backtest.py

# 固定策略回测
python strategy_backtest_fixed.py

# 端到端策略回测
python strategy_end_to_end.py
```

## 4. 实盘交易准备

### 4.1 风险评估
- 单笔仓位限制：20%
- 总仓位限制：80%
- 每日亏损限制：5%
- 佣金率：0.1%
- 滑点：0.05%
- 杠杆倍数：最高 5x（建议 3x 以下）

### 4.2 资金管理
```python
# 在 config/settings.py 中配置
class TradingConfig:
    initial_capital: float = 10000.0
    max_position_size: float = 0.8    # 80% of total capital
    max_single_position: float = 0.2  # 20% per strategy
    paper_trading: bool = True        # 先使用模拟交易
```

### 4.3 交易参数配置
```bash
# 修改 .env 文件
PAPER_TRADING=true          # 先使用模拟交易
MAX_POSITION_SIZE=0.8
MAX_SINGLE_POSITION=0.2
INITIAL_CAPITAL=10000
```

## 5. 实盘交易流程

### 5.1 阶段 1：模拟交易（7天）
```bash
# 运行 AI 交易系统（规则版）
python demo_ai_trading.py

# 运行强化学习演示
python notebooks/demo_rl_research.py
```

### 5.2 阶段 2：低风险实盘（10天）
```bash
# 修改 .env 文件
PAPER_TRADING=false
INITIAL_CAPITAL=10000

# 运行实盘交易示例
node real_trading_example_node.js
```

### 5.3 阶段 3：全功能实盘
```bash
# 运行完整交易系统
python main_trading_system.py
```

## 6. 策略管理

### 6.1 策略选择
项目支持的策略：
- dual_ma：双均线策略（趋势跟踪）
- dual_ma_conservative：保守版双均线（低风险）
- rsi：RSI策略（均值回归）
- rsi_conservative：保守版RSI（低风险）

### 6.2 策略配置
在 `ai_trading/strategy_matcher.py` 中添加/修改策略：
```python
from ai_trading.strategy_matcher import StrategyConfig

new_strategy = StrategyConfig(
    name="my_strategy",
    strategy_class=MyStrategy,
    params={"param1": 10, "param2": 30},
    suitable_trends=["UPTREND", "DOWNTREND"],
    suitable_regimes=["BULL", "BEAR"],
    priority="PRIMARY"
)
```

## 7. 风险控制

### 7.1 止损止盈
- 止损：亏损 5% 自动止损
- 止盈：盈利 10% 自动止盈
- 跟踪止损：价格回撤 3% 自动止损

### 7.2 实时监控
```bash
# 运行网络诊断
node test_network_diag.js

# 运行系统状态检查
npm run indicators
```

### 7.3 熔断机制
- 单日亏损 5%：暂停交易 1小时
- 连续3天亏损：暂停交易 24小时
- 强平风险：立即停止所有交易

## 8. 性能监控

### 8.1 每日检查
- 每日收盘后分析交易记录
- 计算胜率、盈亏比、夏普比率
- 调整策略参数

### 8.2 每周总结
- 每周运行回测检查策略效果
- 调整仓位大小和杠杆倍数
- 更新风险管理参数

## 9. 紧急情况处理

### 9.1 系统故障
- 立即停止所有交易
- 检查网络连接和API状态
- 重启系统并恢复交易

### 9.2 市场异常
- 高度波动市场：暂停杠杆交易
- 极端行情：启动熔断机制
- 流动性风险：停止所有交易

### 9.3 资金安全
- 定期检查账户资金
- 确认所有订单状态
- 验证API密钥和密码安全性

## 10. 技术支持

### 10.1 日志查看
```bash
# 查看系统日志
tail -f logs/system.log

# 查看交易日志
tail -f logs/trading.log
```

### 10.2 调试工具
```bash
# 运行调试模式
npm run test:debug

# 运行特定测试
pytest tests/test_position.py -v
```

### 10.3 社区支持
- 检查项目文档
- 运行演示脚本
- 联系开发团队

## 11. 未来改进

### 11.1 策略优化
- 添加更多Alpha因子
- 优化策略匹配算法
- 改进风险评估模型

### 11.2 系统升级
- 添加更多交易对支持
- 优化执行效率
- 增强容错能力

### 11.3 功能扩展
- 添加期权交易支持
- 优化用户界面
- 增强数据分析功能

## 12. 总结

本实盘交易计划提供了从环境准备到系统运行的完整指南。在开始实盘交易前，请确保：

1. 完成所有测试流程
2. 配置合适的风险参数
3. 先使用模拟交易进行测试
4. 定期检查系统状态
5. 根据市场情况调整策略

---

**注意：** 实盘交易存在风险，请确保您已充分了解相关风险并采取适当的风险控制措施。
