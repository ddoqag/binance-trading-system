# A/B 测试框架使用指南

## 概述

A/B 测试框架集成在 Model Manager 中，支持对 ONNX 模型进行在线 A/B 测试，帮助评估新模型在实际交易环境中的表现。

## 核心功能

- **流量分割**: 支持按比例分配流量到不同模型版本
- **实时指标**: 自动收集延迟、错误率等关键指标
- **无缝切换**: 无需重启即可启动/停止测试
- **版本回滚**: 快速回滚到稳定版本

## 使用示例

### 1. 初始化 Model Manager

```go
config := &ModelConfig{
    ModelDir:       "./models",
    WatchEnabled:   true,
    MaxVersions:    5,
}

mm, err := NewModelManager(config)
if err != nil {
    log.Fatal(err)
}
defer mm.Stop()
mm.Start()
```

### 2. 加载对比模型

```go
ctx := context.Background()

// 加载当前生产模型 (Variant A)
mm.LoadModel(ctx, "sac_agent", "./models/sac_v1.onnx", ModelTypeSAC)

// 加载新模型 (Variant B)
mm.LoadModel(ctx, "sac_agent_v2", "./models/sac_v2.onnx", ModelTypeSAC)

// 获取模型版本 ID
modelsA := mm.ListModels("sac_agent")
modelsB := mm.ListModels("sac_agent_v2")
variantA := modelsA[0].ID
variantB := modelsB[0].ID
```

### 3. 启动 A/B 测试

```go
abConfig := &ABTestConfig{
    Enabled:     true,
    VariantA:    variantA,     // 当前版本
    VariantB:    variantB,     // 新版本
    SplitRatio:  0.2,          // 20% 流量给新版本
    StartTime:   time.Now(),
    Description: "SAC v2 效果验证",
}

if err := mm.StartABTest(abConfig); err != nil {
    log.Fatal(err)
}
```

### 4. 预测时选择模型

```go
func predict(state []float32) (action int, err error) {
    modelID, isABTest := mm.SelectModelForPrediction()
    if modelID == "" {
        return 0, errors.New("no model available")
    }

    start := time.Now()

    // 执行预测 (伪代码)
    model := ort.Load(modelID)
    output := model.Run(state)
    action = argmax(output)

    // 记录指标
    latency := time.Since(start)
    mm.RecordPrediction(modelID, latency, err)

    return action, nil
}
```

### 5. 监控 A/B 测试结果

```go
// 获取实时结果
results := mm.GetABTestResults()
for modelID, result := range results {
    fmt.Printf("Model: %s\n", modelID)
    fmt.Printf("  Requests: %d\n", result.Requests)
    fmt.Printf("  Errors: %d\n", result.Errors)
    fmt.Printf("  Avg Latency: %v\n", result.AvgLatency)
    fmt.Printf("  Error Rate: %.2f%%\n",
        float64(result.Errors)/float64(result.Requests)*100)
}
```

### 6. 逐步放量

```go
// 增加新版本流量到 50%
mm.StopABTest()
abConfig.SplitRatio = 0.5
mm.StartABTest(abConfig)

// 验证后继续增加到 100%
mm.StopABTest()
if err := mm.SwitchModel(variantB); err != nil {
    log.Fatal(err)
}
```

### 7. 异常回滚

```go
// 如果新版本表现不佳，立即回滚
results := mm.GetABTestResults()
if results[variantB].ErrorRate > 0.01 { // 错误率超过 1%
    mm.StopABTest()
    mm.SwitchModel(variantA) // 回滚到旧版本
    log.Println("A/B test failed, rolled back to variant A")
}
```

## 测试策略建议

### 金丝雀发布 (Canary)

```go
// 第一阶段: 5% 流量
abConfig.SplitRatio = 0.05
mm.StartABTest(abConfig)

// 观察 30 分钟后，增加到 25%
abConfig.SplitRatio = 0.25

// 再观察 30 分钟后，增加到 50%
abConfig.SplitRatio = 0.50

// 最后全量发布
mm.SwitchModel(variantB)
```

### 影子测试 (Shadow)

虽然当前实现使用流量分割，但可以扩展到影子测试模式：

```go
// 两个模型都运行，但只有 Variant A 的结果用于交易
// Variant B 的结果只记录指标，不影响实际交易
```

## 关键指标监控

| 指标 | 说明 | 阈值建议 |
|------|------|----------|
| P99 延迟 | 预测延迟 | < 1ms |
| 错误率 | 推理失败比例 | < 0.1% |
| 吞吐量 | 每秒预测次数 | 与线上一致 |
| 夏普比率 | 风险调整后收益 | 新模型 > 旧模型 |
| 最大回撤 | 风险控制 | 新模型 < 旧模型 |

## 与 Prometheus 集成

Model Manager 自动记录以下指标：

```promql
# A/B 测试请求分布
hft_engine_ab_test_requests_total{variant="a"}
hft_engine_ab_test_requests_total{variant="b"}

# 模型推理延迟
histogram_quantile(0.99,
  rate(hft_engine_prediction_latency_seconds_bucket[5m])
)

# 模型加载失败次数
hft_engine_model_load_failures_total
```

## 完整示例

```go
package main

import (
    "context"
    "log"
    "time"
)

func main() {
    // 初始化
    mm, _ := NewModelManager(DefaultModelConfig())
    mm.Start()
    defer mm.Stop()

    ctx := context.Background()

    // 加载模型
    mm.LoadModel(ctx, "production", "models/sac_v1.onnx", ModelTypeSAC)
    mm.LoadModel(ctx, "candidate", "models/sac_v2.onnx", ModelTypeSAC)

    prod := mm.ListModels("production")[0]
    cand := mm.ListModels("candidate")[0]

    // 启动金丝雀测试
    mm.StartABTest(&ABTestConfig{
        Enabled:     true,
        VariantA:    prod.ID,
        VariantB:    cand.ID,
        SplitRatio:  0.1,
        StartTime:   time.Now(),
        Description: "SAC v2 Canary",
    })

    // 运行交易循环
    for i := 0; i < 1000; i++ {
        modelID, _ := mm.SelectModelForPrediction()

        start := time.Now()
        // ... 执行预测
        latency := time.Since(start)

        mm.RecordPrediction(modelID, latency, nil)
    }

    // 检查结果并决策
    results := mm.GetABTestResults()
    if results[cand.ID].AvgLatency < results[prod.ID].AvgLatency {
        log.Println("New model performs better, promoting to production")
        mm.SwitchModel(cand.ID)
    }
}
```

## 注意事项

1. **模型兼容性**: 确保新旧模型输入输出格式一致
2. **资源消耗**: 同时加载两个模型会增加内存使用
3. **状态一致性**: A/B 测试期间，不同请求可能使用不同模型，需确保策略一致性
4. **监控粒度**: 建议按交易对、时间等维度细分监控指标
