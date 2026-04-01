# HFT Execution Alpha 监控系统设置指南

> 本文档基于工业级HFT系统设计，用于实时监控执行质量，回答核心问题：**你的执行是在赚钱，还是在被毒流量吃掉？**

## 系统架构

```text
┌─────────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Go Engine     │────▶│   Metrics   │────▶│ Prometheus  │────▶│   Grafana   │
│  (实时执行层)    │     │  Exporter   │     │  (时序数据库) │     │  (可视化)    │
└─────────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

## 核心监控指标

### 1. Fill Quality (成交质量)

**定义**: `fill_price - mid_price`

| 值 | 含义 |
|---|---|
| < 0 (买单) | 好成交，优于中价 |
| > 0 | 被收割，劣于中价 |

**告警阈值**: `avg(fill_quality) > 0.2`

---

### 2. Adverse Selection (毒流量检测)

**定义**: 成交后价格反向程度

```
adverse_selection = fill_price - future_mid_price(t+Δ)
```

**解读**:
- 正值越大 → 被毒流量碾压越严重
- 接近0 → 公平成交

**告警阈值**: `avg(adverse_selection) > 0.5`

---

### 3. Queue Survival Rate (队列生存率)

**定义**: 成功成交订单占比

```
survival_rate = filled_orders / placed_orders
```

**健康范围**: 20% - 60%
- 过高 → 可能挂价太激进
- 过低 → 队列位置不佳或撤单过早

---

### 4. Cancel Efficiency (撤单效率)

**定义**: 有效撤单占比

```
good_cancel = 撤单后避免了的坏成交
cancel_efficiency = good_cancel / total_cancel
```

---

### 5. Latency Metrics (延迟监控)

| 指标 | 正常范围 | 告警阈值 |
|---|---|---|
| send→ack | < 100ms | > 200ms |
| ack→fill | < 500ms | > 1000ms |
| 总延迟 | < 600ms | > 1200ms |

---

### 6. Inventory Risk (仓位风险)

**监控**:
- 实时仓位大小
- 持仓时间分布
- 仓位集中度

**硬限制**:
```
max_position = 0.01 BTC  (示例)
max_drawdown = 2%
```

---

### 7. PnL Decomposition (盈亏分解)

```
PnL = execution_alpha + strategy_alpha + maker_rebate - adverse_cost - latency_cost
```

| 组件 | 说明 |
|---|---|
| execution_alpha | 执行优势 |
| strategy_alpha | 策略信号收益 |
| maker_rebate | 做市返佣 |
| adverse_cost | 被毒流成本 |
| latency_cost | 延迟成本 |

## Prometheus 配置

### prometheus.yml

```yaml
global:
  scrape_interval: 1s
  evaluation_interval: 1s

scrape_configs:
  - job_name: 'hft_engine'
    static_configs:
      - targets: ['localhost:2112']
    scrape_interval: 1s

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['localhost:9093']

rule_files:
  - 'hft_alerts.yml'
```

### hft_alerts.yml (告警规则)

```yaml
groups:
  - name: hft_execution
    rules:
      - alert: HighAdverseSelection
        expr: avg_over_time(adverse_selection[5m]) > 0.5
        for: 10s
        labels:
          severity: critical
        annotations:
          summary: "High adverse selection detected"
          description: "Avg adverse selection is {{ $value }}"

      - alert: HighLatency
        expr: order_latency_ms > 200
        for: 5s
        labels:
          severity: warning
        annotations:
          summary: "Order latency is high"
          description: "Latency is {{ $value }}ms"

      - alert: LowFillQuality
        expr: fill_quality > 0.2
        for: 30s
        labels:
          severity: warning
        annotations:
          summary: "Fill quality degrading"
          description: "Avg fill quality is {{ $value }}"

      - alert: HighInventory
        expr: abs(position_size) > 0.01
        for: 10s
        labels:
          severity: critical
        annotations:
          summary: "Position size too large"
          description: "Current position: {{ $value }}"

      - alert: KillSwitchTriggered
        expr: drawdown > 0.02
        for: 1s
        labels:
          severity: emergency
        annotations:
          summary: "Kill switch should trigger"
          description: "Drawdown is {{ $value }}"
```

## Grafana 面板设计

### 面板1: Execution Quality Overview

```json
{
  "title": "成交质量概览",
  "panels": [
    {
      "title": "Fill Quality Distribution",
      "type": "histogram",
      "targets": [
        {
          "expr": "fill_quality",
          "legendFormat": "Quality"
        }
      ]
    },
    {
      "title": "Adverse Selection Over Time",
      "type": "timeseries",
      "targets": [
        {
          "expr": "avg_over_time(adverse_selection[1m])",
          "legendFormat": "Adverse"
        }
      ]
    }
  ]
}
```

### 面板2: Latency Analysis

| 图表类型 | 指标 | 用途 |
|---|---|---|
| Time Series | `order_latency_ms` | 延迟趋势 |
| Heatmap | `latency_bucket` | 延迟分布 |
| Gauge | `avg(order_latency_ms)` | 当前平均延迟 |

### 面板3: Queue Performance

```
Metrics:
- queue_survival_rate
- filled_orders_total
- canceled_orders_total
- avg_queue_position
```

### 面板4: PnL Attribution

**饼图展示**:
- Execution Alpha: 40%
- Strategy Alpha: 30%
- Rebate: 20%
- Costs: -10%

### 面板5: Real-time Risk

**Gauge 仪表盘**:
- Position Size: [-max, +max]
- Drawdown: [0%, 5%]
- Order Frequency: orders/sec

## Go Engine 指标导出代码

### metrics.go

```go
package main

import (
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "net/http"
)

var (
    // Fill Quality
    fillQuality = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "fill_quality",
            Help:    "Fill price relative to mid price",
            Buckets: prometheus.LinearBuckets(-1, 0.1, 21),
        },
        []string{"side"},
    )

    // Adverse Selection
    adverseSelection = prometheus.NewHistogram(
        prometheus.HistogramOpts{
            Name:    "adverse_selection",
            Help:    "Price movement after fill",
            Buckets: prometheus.LinearBuckets(-2, 0.2, 21),
        },
    )

    // Latency
    orderLatency = prometheus.NewHistogramVec(
        prometheus.HistogramOpts{
            Name:    "order_latency_ms",
            Help:    "Order latency in milliseconds",
            Buckets: []float64{10, 25, 50, 100, 200, 500, 1000, 2000},
        },
        []string{"stage"}, // "ack", "fill"
    )

    // Position
    positionGauge = prometheus.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "position_size",
            Help: "Current position size",
        },
        []string{"symbol"},
    )

    // Order Counts
    ordersTotal = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "orders_total",
            Help: "Total number of orders",
        },
        []string{"status"}, // "placed", "filled", "canceled"
    )

    // PnL
    pnlGauge = prometheus.NewGaugeVec(
        prometheus.GaugeOpts{
            Name: "pnl",
            Help: "Profit and loss",
        },
        []string{"type"}, // "realized", "unrealized"
    )
)

func InitMetrics() {
    prometheus.MustRegister(fillQuality)
    prometheus.MustRegister(adverseSelection)
    prometheus.MustRegister(orderLatency)
    prometheus.MustRegister(positionGauge)
    prometheus.MustRegister(ordersTotal)
    prometheus.MustRegister(pnlGauge)
}

func StartMetricsServer(port string) {
    http.Handle("/metrics", promhttp.Handler())
    go http.ListenAndServe(":"+port, nil)
}
```

### 指标上报示例

```go
// 成交时上报
func OnOrderFilled(fillPrice, midPrice float64, side string) {
    quality := fillPrice - midPrice
    if side == "SELL" {
        quality = -quality
    }
    fillQuality.WithLabelValues(side).Observe(quality)
    ordersTotal.WithLabelValues("filled").Inc()
}

// 延迟上报
func RecordLatency(stage string, latencyMs float64) {
    orderLatency.WithLabelValues(stage).Observe(latencyMs)
}

// 仓位更新
func UpdatePosition(symbol string, size float64) {
    positionGauge.WithLabelValues(symbol).Set(size)
}

// PnL更新
func UpdatePnL(realized, unrealized float64) {
    pnlGauge.WithLabelValues("realized").Set(realized)
    pnlGauge.WithLabelValues("unrealized").Set(unrealized)
}
```

## 部署步骤

### 1. 启动 Prometheus

```bash
docker run -d \
  --name=prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v $(pwd)/hft_alerts.yml:/etc/prometheus/hft_alerts.yml \
  prom/prometheus
```

### 2. 启动 Grafana

```bash
docker run -d \
  --name=grafana \
  -p 3000:3000 \
  -e GF_SECURITY_ADMIN_PASSWORD=admin \
  grafana/grafana
```

### 3. 配置数据源

1. 访问 http://localhost:3000
2. 登录: admin/admin
3. Configuration → Data Sources
4. Add Prometheus
5. URL: http://localhost:9090
6. Save & Test

### 4. 导入面板

1. Create → Import
2. 上传面板JSON或输入ID
3. 选择Prometheus数据源
4. Import

## 关键观察指标

### ❌ 被收割的迹象

```
fill_quality > 0
adverse_selection > 0
PnL ↓
queue_survival < 10%
```

### ✅ 正常执行的迹象

```
fill_quality ≈ 0 or < 0
adverse_selection ≈ 0
PnL ↑
queue_survival 20-60%
```

### ⚠️ 需要调整的迹象

```
high latency → 检查网络/交易所连接
low fill rate → 调整挂单位置
high inventory → 收紧风控
high cancel rate → 优化撤单策略
```

## 与风控系统的联动

```go
// 监控指标触发风控
if avgAdverse > 0.5 {
    riskManager.ReduceExposure(0.5)
}

if avgLatency > 200 {
    riskManager.IncreaseSafetyMargin()
}

if drawdown > 0.02 {
    riskManager.KillSwitch()
}
```

## 总结

> **你不是在监控策略，你在监控"执行是否被市场利用"**

真正的差距在于：**谁更快发现自己在亏钱**

通过这套监控系统，你可以：
1. 实时发现被毒流量收割
2. 量化执行alpha的真实来源
3. 快速定位系统性能瓶颈
4. 自动化风控响应

---

**下一步**: 将 Execution Alpha 指标接入 SAC 训练闭环，让模型学会主动避免毒流
