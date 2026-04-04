# Self-Evolving Trader 项目升级总路线图

> 本文档汇总了从研究级信号系统到工业级自适应执行交易生态系统的完整升级路径。

---

## 一、升级全景图

```
Phase A          Phase B               Phase C                      Phase D
Checkpoint    →  Execution Engine   →  Live Operation Layer    →  Autonomous RL Layer
(状态持久化)      (执行引擎)              (实盘操作层)                   (自主决策层)
┌──────────┐   ┌─────────────────┐   ┌──────────────────────┐   ┌─────────────────┐
│ Save/Load│   │ Queue Model     │   │ User Data Stream     │   │ Execution Gym   │
│ HMM/PBT  │ → │ Fill Model      │ → │ Order State Machine  │ → │ SAC Agent       │
│ JSON/pkl │   │ Slippage Model  │   │ Cancel / Reprice     │   │ Online Training │
│ Auto-save│   │ ExecutionPolicy │   │ Queue Tracker        │   │ ONNX Export     │
└──────────┘   └─────────────────┘   └──────────────────────┘   └─────────────────┘
      │                │                         │                      │
      └────────────────┴─────────────────────────┴──────────────────────┘
                                    ↓
                    ┌───────────────────────────────┐
                    │   Production-Grade Trader     │
                    │   (信号 + 执行 + 状态 + RL)    │
                    └───────────────────────────────┘
```

---

## 二、各阶段目标与核心产出

### Phase A: Checkpoint 状态持久化（已完成 ✅）

**目标**：让进化状态在进程崩溃/重启后能够恢复，避免"一夜回到解放前"。

**核心产出**：
- `self_evolving_trader.py` 中的 `save_checkpoint()` / `load_checkpoint()` / `_auto_save_loop()`
- 时间戳分目录结构：`checkpoints/YYYYMMDD_HHMMSS_*/`
- 5 个持久化文件：
  - `trader_state.json` — TradingStats / runtime info
  - `meta_agent.json` — 策略权重与完整 performance tracker
  - `pbt_population.json` — PBT 种群与精英配置
  - `regime_detector.pkl` — HMM + GARCH 参数
  - `civilization.json` — Agent Civilization 状态

**验证标准**：
- [x] 运行 trader 60 秒后 `checkpoints/` 出现时间戳目录
- [x] Ctrl+C 保存成功
- [x] 重启后 `total_cycles` 正确恢复

---

### Phase B: Execution Engine 升级（已完成 ✅）

**目标**：把纯信号系统升级为"信号 + 执行"系统，具备 Binance 实盘下单能力。

**核心产出**：
- `core/execution_models.py` — `Order`、`OrderBook` 标准化结构
- `core/queue_model.py` — FIFO 队列位置估算
- `core/fill_model.py` — Hazard Rate 成交概率模型
- `core/slippage_model.py` — 市价单执行均价与滑点估计
- `core/execution_policy.py` — 规则版执行决策引擎
- `core/binance_rest_client.py` — HMAC 签名 REST 客户端
- `core/binance_ws_client.py` — L2 OrderBook + Trade Stream WebSocket
- 文档：`docs/EXECUTION_ENGINE_UPGRADE_GUIDE.md`

**验证标准**：
- [x] 7 个执行引擎文件通过 `py_compile`
- [x] `ExecutionPolicy.decide()` 能输出 MARKET / LIMIT / WAIT 决策
- [x] REST 客户端能正确生成 HMAC-SHA256 签名

---

### Phase C: 实盘操作层（文档已完成，待实现 ⏳）

**目标**：建立精确的订单生命周期追踪、自动撤单与智能重挂能力，摆脱"盲打"。

**核心产出**：
- `core/binance_user_data_client.py` — `listenKey` 管理与 `executionReport` 监听
- `core/order_state_machine.py` — 订单状态机 (NEW → OPEN → PARTIALLY_FILLED → FILLED / CANCELED)
- `core/position_manager.py` — 持仓精确追踪
- `core/queue_tracker.py` — 基于 L2 diff 的队列位置实时跟踪
- `core/cancel_manager.py` — 撤单决策器（覆盖信号反转、状态剧变、排队超时、毒流、价格偏离）
- `core/reprice_engine.py` — 重挂定价引擎
- `core/order_lifecycle_manager.py` — Cancel / Reprice 统一封装
- 文档：
  - `docs/USER_DATA_STREAM_AND_OSM_GUIDE.md`
  - `docs/CANCEL_REPRICE_GUIDE.md`

**验证标准（待完成）**：
- [ ] User Data Stream 在 30 分钟周期内稳定不掉线
- [ ] `executionReport` 能正确驱动 OSM 状态流转
- [ ] 开一家限价单，模拟信号反转后触发自动撤单
- [ ] 撤单后未成交部分正确重挂，quantity 无误

---

### Phase D: 自主 RL 决策层（文档已完成，待实现 ⏳）

**目标**：用 SAC 强化学习替代固定阈值规则，学习最优的下单/撤单/重挂/观望策略。

**核心产出**：
- `rl/execution_env.py` — Execution Gym 环境（10-dim state, 4-dim action）
- `rl/sac_agent.py` — Soft Actor-Critic 实现（Twin Critics + Auto Alpha）
- `rl/train_sac_execution.py` — 训练脚本
- 文档：`docs/SAC_EXECUTION_RL_GUIDE.md`

**验证标准（待完成）**：
- [ ] SAC 在简化 L2 数据上训练收敛
- [ ] Eval reward 稳定高于随机/规则基准
- [ ] Actor 可导出为 ONNX 供 Go Engine 推理
- [ ] 推理动作经 post-process 后始终合法

---

## 三、文件矩阵：谁依赖谁

```
self_evolving_trader.py
├── Phase A: CheckpointManager
│   ├── regime_detector.save/load
│   ├── meta_agent.export_state/import_state
│   ├── pbt_trainer.save_checkpoint/load_checkpoint
│   └── civilization.export_state/import_state
│
├── Phase B: Execution Engine
│   ├── execution_policy.decide()
│   ├── queue_model + fill_model + slippage_model
│   ├── binance_rest_client.place_order()
│   └── binance_ws_client (book + trade)
│
├── Phase C: Live Operation
│   ├── binance_user_data_client (executionReport)
│   ├── order_state_machine (handle_execution_report)
│   ├── position_manager (handle_account_position)
│   ├── queue_tracker (update_on_book / update_on_trade)
│   ├── cancel_manager.evaluate()
│   ├── reprice_engine.reprice()
│   └── order_lifecycle_manager (check_and_cancel / reprice_order)
│
└── Phase D: RL Layer
    ├── sac_agent.select_action()
    └── execution_env.step()  (用于离线训练)
```

---

## 四、推荐实施顺序

### 阶段 1: 实现 User Data Stream + OSM（阻塞项）
 Cancelling 和 Repricing 的前提是精确的订单状态追踪。**没有 OSM，Cancel Manager 就是瞎子。**

1. 实现 `binance_user_data_client.py` 并接入 `listenKey`
2. 实现 `order_state_machine.py` 和 `position_manager.py`
3. 在 `self_evolving_trader.py` 中初始化并绑定回调
4. 跑 paper trading 验证 `executionReport` 流转正确

### 阶段 2: 实现 Cancel / Reprice（核心武器）
 这是降低"无效排队"成本和 adverse selection 的关键。

1. 实现 `queue_tracker.py` 并与 `ws_client.book` 绑定
2. 实现 `cancel_manager.py` 和 `reprice_engine.py`
3. 实现 `order_lifecycle_manager.py` 统一调度
4. 在 `_trading_cycle()` 中插入 cancel-before-new-order 逻辑
5. 跑 paper trading 观察 cancel 频率和重挂正确率

### 阶段 3: 实现 SAC Execution RL（质变点）
 用 RL 替代硬编码规则，让系统自动适应不同 symbol 和时间段。

1. 收集 1-2 周 Level 2 历史数据
2. 填充 `execution_env.py` 中 regime / OFI / adverse_score 等占位符
3. 训练 SAC，记录 eval reward 曲线
4. 对比 SAC 决策 vs `ExecutionPolicy` 规则决策的 fill quality
5. 导出 ONNX，尝试在 `core_go/` 中做低延迟推理（可选）

---

## 五、风险与降级策略

| 风险 | 影响 | 降级方案 |
|------|------|----------|
| User Data Stream 断线 | 订单状态丢失 | 用 REST `get_open_orders()` 定期同步校准 |
| Cancel API 延迟 > 200ms | 该撤未撤 | 收紧前置条件，提前发起 cancel |
| RL 模型未收敛 | 动作混乱 | 自动 fallback 到 `ExecutionPolicy` 规则版 |
| QueueTracker 估算偏差 | cancel 决策错误 | 调大 `max_queue_wait_seconds` 容忍窗口 |
| Binance rate limit | 新单/cancel 被拒 | 本地请求队列 + 指数退避 |

---

## 六、文档索引

| 文档 | 阶段 | 内容 |
|------|------|------|
| `EXECUTION_ENGINE_UPGRADE_GUIDE.md` | Phase B | Queue/Fill/Slippage 模型 + Binance 接入 |
| `USER_DATA_STREAM_AND_OSM_GUIDE.md` | Phase C | User Data Stream + Order State Machine |
| `CANCEL_REPRICE_GUIDE.md` | Phase C | Queue Tracker + Cancel Manager + Reprice Engine |
| `SAC_EXECUTION_RL_GUIDE.md` | Phase D | Execution Gym + SAC Agent + 训练流程 |
| `MASTER_PROJECT_UPGRADE_ROADMAP.md` | All | 本文件，总览与实施计划 |

---

## 七、演进优先级（MoSCoW）

### Must Have
- [x] Checkpoint 持久化
- [x] Execution Engine 核心模型
- [ ] User Data Stream 接入
- [ ] Order State Machine

### Should Have
- [ ] Cancel / Reprice 引擎
- [ ] Queue Tracker 实时跟踪

### Could Have
- [ ] SAC Execution RL 离线训练
- [ ] SAC Actor ONNX 导出

### Won't Have (this quarter)
- Go Engine 上的 RL 推理（需先完成 `shared/` mmap 协议）
- 多资产并行执行优化
- 对抗训练（纳什均衡防御）

---

## 八、成功标准

完成全部文档 + 实现后，系统应具备以下能力：

1. **可恢复**：重启后状态完全恢复，继续交易不丢失上下文
2. **可执行**：信号能自动转化为 Binance 订单，支持 LIMIT / MARKET
3. **可追踪**：每个订单的完整生命周期精确到毫秒级状态
4. **可调整**：信号反转、排队过深、市场剧变时自动撤单重挂
5. **可学习**：离线训练的 SAC 模型能给出优于规则版的执行决策

---

*文档版本: v1.0*
*适用项目: binance/new Self-Evolving Trader*
*创建日期: 2026-04-02*
