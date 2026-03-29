# 项目脚本参考
<!-- AUTO-GENERATED - DO NOT EDIT -->

## Node.js 脚本

| 命令 | 描述 |
|------|------|
| `npm test` | Run Playwright tests |
| `npm run test:ui` | Run Playwright tests with UI |
| `npm run test:headed` | Run Playwright tests with browser visible |
| `npm run test:debug` | Run Playwright tests in debug mode |
| `npm run docs` | Download Binance SDK documentation |
| `npm run fetch-db` | Fetch market data from Binance API and save to database |
| `npm run test-db` | Test database connection |
| `npm run init-db` | Initialize database |
| `npm run migrate-db` | Migrate indicator table |
| `npm run indicators` | Calculate technical indicators |
| `npm start` | Start main Node.js application |
| `npm run demo:core` | Run core client demo |
| `npm run demo:ws` | Run WebSocket demo |
| `npm run demo:real` | Run real trading example |
| `npm run demo:real:simple` | Run simple real trading example |
| `npm run test:core` | Run core client tests |
| `npm run test:core:simple` | Run simple core client tests |
| `npm run test:core` | Run core client tests |
| `npm run test:core:simple` | Run simple core client tests |

## Python 脚本

| 命令 | 描述 |
|------|------|
| `python demo_standalone.py` | 独立演示（无外部依赖） |
| `python main_trading_system.py` | 完整交易系统（带回测） |
| `python strategy_simple_backtest.py` | 简单回测 |
| `python strategy_end_to_end.py` | 端到端策略回测 |
| `python strategy_backtest_fixed.py` | 固定策略回测 |
| `python verify_structure.py` | 验证项目结构 |
| `python test_modules.py` | 运行模块测试 |
| `python testnet_demo.py` | 币安测试网演示 |
| `python notebooks/demo_factor_research.py` | 因子研究演示 |
| `python notebooks/demo_rl_research.py` | RL 研究演示（需要 PyTorch） |
| `python demo_ai_trading.py` | AI驱动的交易系统演示（规则版） |
| `python demo_leverage_trading.py` | 杠杆交易执行器演示（做多/做空/全仓杠杆） |
| `python demo_phase4_phase5.py` | Phase 4 & 5 集成演示（RL决策融合 + 高频执行） |
| `pytest tests/ -v` | 运行所有 Python 测试 |
| `pytest tests/test_position.py -v` | 运行特定测试文件 |
| `pytest tests/ --cov` | 运行测试并生成覆盖率报告 |
| `pytest tests/ -k "test_position"` | 运行匹配模式的测试 |

## Redis 测试脚本

| 命令 | 描述 |
|------|------|
| `python test_redis_simple.py` | 简单 Redis 连接测试 |
| `python test_redis_python.py` | Python Redis 管理器测试 |
| `node test_redis_connection.js` | Node.js Redis 连接测试 |
| `wsl --user root bash -c "cd /mnt/d/binance && ./test_redis_wsl.sh"` | 完整 WSL2 Redis 测试 |

