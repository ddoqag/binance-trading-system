# AutoResearch Trading - 自主交易研究框架

基于 karpathy/autoresearch 理念的交易系统自优化框架。

## 核心理念

1. **固定时间预算**：每次实验运行固定时长（如30分钟）
2. **单一文件修改**：只修改 `self_evolving_meta_agent.py` 的评估参数
3. **自动化迭代**：AI自主调整参数，保留好的，丢弃差的
4. **永不停止**：24/7运行，持续优化

## 实验循环

```
LOOP FOREVER:
    1. 读取当前配置和历史结果
    2. 提出新的参数调整方案
    3. 修改配置并运行30分钟
    4. 评估指标：稳定性评分 + 策略多样性 + 市场适应性
    5. 记录结果到 results.tsv
    6. 结果好 → git commit keep
    7. 结果差 → git reset discard
```

## 评估指标

| 指标 | 目标 | 说明 |
|------|------|------|
| stability_score | >70 | 系统稳定性评分 |
| effective_n | >4 | 有效策略数量 |
| hhi | 0.15-0.25 | 集中度指数 |
| regime_accuracy | >80% | 市场状态识别准确率 |
| ml_performance | >1.0 | ML策略相对表现 |

## 可调参数

```yaml
# config/signal_evaluation.yaml
signal_scoring:
  weights:
    accuracy: 0.35      # 可调整
    consistency: 0.40   # 可调整
    strength: 0.25      # 可调整

  decay_lambda: 0.8     # 时间衰减因子
  max_single_weight: 0.60
  min_single_weight: 0.05
  exploration_noise: 0.05
```

## 文件结构

```
autoresearch_trading.py  # 实验控制器（AI修改）
experiment_runner.py     # 运行单个实验
results.tsv              # 实验结果记录
AUTORESEARCH_TRADING.md  # 本文件（人类指导）
```

## 快速开始

```bash
# 1. 创建实验分支
git checkout -b autoresearch/apr4

# 2. 初始化结果文件
echo "commit	stability_score	effective_n	hhi	status	description" > results.tsv

# 3. 启动自主研究
python autoresearch_trading.py
```
