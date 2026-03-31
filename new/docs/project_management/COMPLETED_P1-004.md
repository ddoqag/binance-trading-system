# P1-004: 错误重试机制 - 完成记录

## 任务概述

实现智能错误重试机制，为 API 调用提供指数退避、错误分类、断路器集成等功能，确保在遇到瞬态故障时能够自动恢复，同时避免对系统或 API 端点造成过大压力。

## 完成日期

2026-03-30

## 实现内容

### 1. 重试策略 (`retry.go`)

#### 三种预设策略

| 策略 | MaxRetries | InitialDelay | MaxDelay | BackoffMultiplier | 适用场景 |
|------|------------|--------------|----------|-------------------|----------|
| Default | 3 | 500ms | 30s | 2.0 | 一般 API 调用 |
| Aggressive | 5 | 200ms | 10s | 1.5 | 订单操作（关键） |
| Conservative | 2 | 1s | 60s | 2.0 | 非关键查询 |

#### 指数退避算法
```go
func (re *RetryExecutor) calculateDelay(attempt int, retryType RetryableErrorType) time.Duration {
    // 基础指数退避
    delay := re.policy.InitialDelay
    for i := 0; i < attempt; i++ {
        delay = time.Duration(float64(delay) * re.policy.BackoffMultiplier)
    }

    // 错误类型特定乘数
    switch retryType {
    case RetryableErrorRateLimit:
        delay = delay * 2  // 速率限制需要更长时间等待
    case RetryableErrorServer:
        delay = delay * 3 / 2  // 服务器错误需要额外时间
    }

    // 添加 jitter 防止惊群效应
    if re.policy.JitterFactor > 0 {
        jitter := time.Duration(float64(delay) * re.policy.JitterFactor * (0.5 + randFloat()))
        delay = delay + jitter
    }

    return min(delay, re.policy.MaxDelay)
}
```

### 2. 错误分类系统

#### 五种错误类型
```go
const (
    RetryableErrorNone RetryableErrorType = iota      // 不可重试
    RetryableErrorServer                               // 5xx 服务器错误
    RetryableErrorRateLimit                            // 429 速率限制
    RetryableErrorNetwork                              // 网络/超时错误
    RetryableErrorTemporary                            // 临时错误
)
```

#### 可重试错误模式
- **HTTP 状态码**: 429, 500, 502, 503, 504
- **网络错误**: timeout, connection reset, connection refused
- **服务器错误**: service unavailable, gateway error, rate limit

#### 不可重试错误模式
- **客户端错误**: invalid api key, invalid signature, unauthorized
- **业务错误**: insufficient balance, invalid symbol, min notional
- **上下文错误**: context.Canceled, context.DeadlineExceeded

### 3. Binance API 错误解析

```go
type BinanceAPIError struct {
    Code    int    `json:"code"`
    Message string `json:"msg"`
    Status  int    // HTTP 状态码
}

func (e *BinanceAPIError) IsRetryable() bool {
    // 已知可重试错误码
    retryableCodes := map[int]bool{
        -1001: true, // Internal error
        -1003: true, // Rate limit exceeded
        -1006: true, // Server busy
        -1007: true, // Timeout
        -1016: true, // Service shutting down
        -1021: true, // Timestamp error
    }
    // ...
}
```

### 4. 断路器集成

与现有 `degrade.go` 中的 CircuitBreaker 无缝集成：

```go
func TestRetryExecutor_WithCircuitBreaker(t *testing.T) {
    cb := NewCircuitBreaker("test", 2, 100*time.Millisecond)
    executor := NewRetryExecutor(policy, cb)

    // 连续失败触发断路器打开
    // 后续请求立即失败，避免资源浪费
}
```

### 5. 端点特定重试管理

```go
type PerEndpointRetryManager struct {
    policies   map[string]*RetryPolicy
    executors  map[string]*RetryExecutor
}

// 为不同端点配置不同策略
manager.SetPolicy("/api/v3/order", AggressiveRetryPolicy())      // 订单：激进重试
manager.SetPolicy("/api/v3/account", DefaultRetryPolicy())       // 账户：默认策略
manager.SetPolicy("/api/v3/ticker", ConservativeRetryPolicy())   // 行情：保守策略
```

### 6. 线程安全统计

```go
type RetryStats struct {
    TotalAttempts   int
    SuccessCount    int
    FailureCount    int
    RetryCount      int
    mu              sync.RWMutex
}

func (rs *RetryStats) GetStats() map[string]interface{} {
    // 返回包含成功率的统计信息
    // success_rate: "50.0%"
}
```

## 测试覆盖

### 测试文件

- `retry_test.go`: 17 项测试

### 测试结果

```
=== RUN   TestErrorClassifier_Classify
--- PASS: TestErrorClassifier_Classify (0.00s)
=== RUN   TestErrorClassifier_IsRetryable
--- PASS: TestErrorClassifier_IsRetryable (0.00s)
=== RUN   TestRetryPolicy_Default
--- PASS: TestRetryPolicy_Default (0.00s)
=== RUN   TestRetryPolicy_Aggressive
--- PASS: TestRetryPolicy_Aggressive (0.00s)
=== RUN   TestRetryExecutor_Execute_Success
--- PASS: TestRetryExecutor_Execute_Success (0.00s)
=== RUN   TestRetryExecutor_Execute_RetrySuccess
--- PASS: TestRetryExecutor_Execute_RetrySuccess (0.05s)
=== RUN   TestRetryExecutor_Execute_MaxRetries
--- PASS: TestRetryExecutor_Execute_MaxRetries (0.05s)
=== RUN   TestRetryExecutor_Execute_NonRetryable
--- PASS: TestRetryExecutor_Execute_NonRetryable (0.00s)
=== RUN   TestRetryExecutor_Execute_ContextCancellation
--- PASS: TestRetryExecutor_Execute_ContextCancellation (0.05s)
=== RUN   TestRetryExecutor_CalculateDelay
--- PASS: TestRetryExecutor_CalculateDelay (0.00s)
=== RUN   TestRetryExecutor_WithCircuitBreaker
--- PASS: TestRetryExecutor_WithCircuitBreaker (0.05s)
=== RUN   TestRetryStats
--- PASS: TestRetryStats (0.00s)
=== RUN   TestPerEndpointRetryManager
--- PASS: TestPerEndpointRetryManager (0.00s)
=== RUN   TestBinanceAPIError
--- PASS: TestBinanceAPIError (0.00s)
=== RUN   TestRetryExecutor_ConcurrentAccess
--- PASS: TestRetryExecutor_ConcurrentAccess (0.00s)
=== RUN   TestRetryableErrorType_String
--- PASS: TestRetryableErrorType_String (0.00s)
=== RUN   TestRetryExecutor_ExecuteWithResult
--- PASS: TestRetryExecutor_ExecuteWithResult (0.02s)

PASS
ok      hft_engine      2.965s
```

**测试通过率**: 100% (17/17)

### 测试场景覆盖

| 测试 | 场景 |
|------|------|
| Classify | 错误分类准确性（10种错误类型） |
| IsRetryable | 可重试/不可重试判断 |
| Execute_Success | 首次执行成功 |
| Execute_RetrySuccess | 重试后成功 |
| Execute_MaxRetries | 达到最大重试次数 |
| Execute_NonRetryable | 非可重试错误立即失败 |
| Execute_ContextCancellation | 上下文取消处理 |
| CalculateDelay | 指数退避计算 |
| WithCircuitBreaker | 断路器集成 |
| RetryStats | 统计信息准确性 |
| PerEndpointRetryManager | 端点特定策略 |
| BinanceAPIError | API 错误解析 |
| ConcurrentAccess | 并发安全 |

## 集成验证

- [x] 编译通过: `go build -o hft_engine.exe .`
- [x] 所有测试通过: `go test -v ./...`
- [x] 与 CircuitBreaker 集成验证
- [x] 与 RequestQueue 限速系统集成验证
- [x] 上下文取消处理验证

## 使用示例

### 基本使用
```go
// 使用默认策略
policy := DefaultRetryPolicy()
executor := NewRetryExecutor(policy, nil)

ctx := context.Background()
err := executor.Execute(ctx, func() error {
    // 你的 API 调用
    return callBinanceAPI()
})
```

### 带结果的执行
```go
result, err := executor.ExecuteWithResult(ctx, func() (interface{}, error) {
    return fetchAccountInfo()
})
```

### 全局端点管理
```go
manager := GetGlobalRetryManager()

// 执行请求，自动应用端点对应策略
err := manager.Execute(ctx, "/api/v3/order", func() error {
    return placeOrder()
})
```

### 与断路器一起使用
```go
cb := NewCircuitBreaker("api", 5, 30*time.Second)
executor := NewRetryExecutor(AggressiveRetryPolicy(), cb)

err := executor.Execute(ctx, criticalOperation)
```

## 架构影响

### 无破坏性变更
- 完全向后兼容，现有代码无需修改
- 新增功能为增强特性，不影响原有流程

### 性能影响
- 错误分类开销极小（字符串匹配）
- 退避等待在独立 goroutine 中执行
- 统计数据使用 RWMutex，读操作无锁

## 风险缓解

| 风险 | 缓解措施 |
|------|----------|
| 重试风暴导致 API 限流 | 指数退避 + Jitter + 最大重试次数 |
| 持续失败浪费资源 | 与断路器集成，快速失败 |
| 非可重试错误重复请求 | 精确错误分类，立即返回 |
| 上下文取消未处理 | 每次重试前检查 ctx.Done() |

## 后续工作

- **P1-006**: 集成测试 - 基于当前重试机制进行完整集成测试

## 备注

错误重试机制现已完整集成到 HFT 引擎，提供智能的错误处理策略：
- **自动重试**: 对瞬态故障自动恢复
- **快速失败**: 对业务错误立即返回
- **资源保护**: 通过断路器防止级联故障
- **灵活配置**: 支持端点特定策略

