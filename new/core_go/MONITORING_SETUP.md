# HFT 交易系统监控配置指南

## 概述

本监控系统基于 Prometheus + Grafana + Alertmanager 构建，提供完整的 HFT 交易系统可观测性。

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        监控架构                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│   │  HFT Engine │────▶│  Prometheus │────▶│   Grafana   │       │
│   │   (Go)      │     │  (TSDB)     │     │ (Dashboard) │       │
│   └─────────────┘     └──────┬──────┘     └─────────────┘       │
│                              │                                    │
│                              ▼                                    │
│                        ┌─────────────┐                           │
│                        │ Alertmanager│                           │
│                        └──────┬──────┘                           │
│                               │                                   │
│                    ┌─────────┼─────────┐                         │
│                    ▼         ▼         ▼                         │
│               ┌────────┐ ┌────────┐ ┌────────┐                  │
│               │ Slack  │ │ Email  │ │Webhook │                  │
│               └────────┘ └────────┘ └────────┘                  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## 配置文件

| 文件 | 用途 |
|------|------|
| `prometheus.yml` | Prometheus 主配置 |
| `alert_rules.yml` | 告警规则定义 |
| `alertmanager.yml` | 告警通知路由 |
| `grafana_dashboard.json` | Grafana 仪表板 |

## 快速启动

### 1. 启动 Prometheus

```bash
# 下载 Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.51.0/prometheus-2.51.0.linux-amd64.tar.gz
tar xvfz prometheus-2.51.0.linux-amd64.tar.gz
cd prometheus-2.51.0.linux-amd64

# 复制配置文件
cp /path/to/core_go/prometheus.yml ./
cp /path/to/core_go/alert_rules.yml ./

# 启动
./prometheus --config.file=prometheus.yml
```

### 2. 启动 Alertmanager

```bash
# 下载 Alertmanager
wget https://github.com/prometheus/alertmanager/releases/download/v0.27.0/alertmanager-0.27.0.linux-amd64.tar.gz
tar xvfz alertmanager-0.27.0.linux-amd64.tar.gz
cd alertmanager-0.27.0.linux-amd64

# 复制配置文件
cp /path/to/core_go/alertmanager.yml ./

# 启动
./alertmanager --config.file=alertmanager.yml
```

### 3. 启动 Grafana

```bash
# Docker 启动
docker run -d \
  -p 3000:3000 \
  --name=grafana \
  -e "GF_SECURITY_ADMIN_PASSWORD=admin" \
  grafana/grafana:latest

# 导入仪表板
# 1. 登录 http://localhost:3000 (admin/admin)
# 2. Configuration → Data Sources → Add data source → Prometheus
# 3. URL: http://localhost:9090 → Save & Test
# 4. + → Import → Upload JSON file → 选择 grafana_dashboard.json
```

## 告警规则说明

### 系统健康告警

| 告警名称 | 严重程度 | 触发条件 | 说明 |
|----------|----------|----------|------|
| HFTSystemDegraded | Warning | 降级级别 > 0 | 系统进入降级模式 |
| HFTSystemEmergency | Critical | 降级级别 == 3 | 系统紧急状态，交易暂停 |
| ComponentUnhealthy | Warning | 组件状态 > 2 | 组件不健康 |
| ComponentFailed | Critical | 组件状态 == 4 | 组件故障 |

### 风控告警

| 告警名称 | 严重程度 | 触发条件 | 说明 |
|----------|----------|----------|------|
| DailyDrawdownHigh | Warning | 日回撤 > 3% | 回撤过高警告 |
| DailyDrawdownCritical | Critical | 日回撤 > 5% | 回撤临界，建议暂停 |
| MaxDrawdownExceeded | Critical | 最大回撤 > 15% | 超过最大回撤限制 |
| MarginUsageHigh | Warning | 保证金使用率 > 70% | 建议降低仓位 |
| MarginUsageCritical | Critical | 保证金使用率 > 85% | 爆仓风险 |
| LeverageHigh | Warning | 杠杆 > 5x | 杠杆过高 |

### 交易告警

| 告警名称 | 严重程度 | 触发条件 | 说明 |
|----------|----------|----------|------|
| OrderRejectionRateHigh | Warning | 拒绝率 > 10% | 订单被拒绝过多 |
| OrderLatencyHigh | Warning | P99 延迟 > 100ms | 订单延迟过高 |
| FillLatencyHigh | Warning | P99 成交延迟 > 500ms | 成交延迟过高 |
| WebSocketDisconnected | Critical | WebSocket 断开 | 无法接收实时数据 |

### 预测系统告警

| 告警名称 | 严重程度 | 触发条件 | 说明 |
|----------|----------|----------|------|
| PredictionLatencyHigh | Warning | P99 预测延迟 > 1ms | 模型推理延迟过高 |
| ModelLoadFailure | Critical | 模型加载失败 | 无法加载模型文件 |
| ABTestImbalance | Info | 流量差异 > 20% | A/B 测试流量不均衡 |

## 通知配置

### Webhook 接收示例

```go
package main

import (
    "encoding/json"
    "log"
    "net/http"
)

type Alert struct {
    Labels      map[string]string `json:"labels"`
    Annotations map[string]string `json:"annotations"`
    Status      string            `json:"status"`
}

type WebhookPayload struct {
    Alerts []Alert `json:"alerts"`
}

func alertHandler(w http.ResponseWriter, r *http.Request) {
    var payload WebhookPayload
    if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }

    for _, alert := range payload.Alerts {
        log.Printf("[%s] %s: %s",
            alert.Status,
            alert.Labels["severity"],
            alert.Annotations["summary"])
    }
}

func main() {
    http.HandleFunc("/alerts/webhook", alertHandler)
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

### Slack 配置

1. 创建 Slack Incoming Webhook
2. 在 `alertmanager.yml` 中配置:

```yaml
global:
  slack_api_url: 'YOUR_WEBHOOK_URL'

receivers:
  - name: 'critical-alerts'
    slack_configs:
      - channel: '#hft-alerts'
        title: 'HFT Critical Alert'
        text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

### Email 配置

```yaml
global:
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@your-system.com'
  smtp_auth_username: 'your-email@gmail.com'
  smtp_auth_password: 'your-app-password'

receivers:
  - name: 'risk-team'
    email_configs:
      - to: 'risk@your-company.com'
        subject: 'HFT Risk Alert'
```

## 常用查询

### PromQL 示例

```promql
# 当前日回撤
hft_engine_daily_drawdown

# 过去5分钟订单率
sum(rate(hft_engine_orders_total[5m]))

# P99 订单延迟
histogram_quantile(0.99, rate(hft_engine_order_latency_seconds_bucket[5m]))

# 各币种未实现盈亏
hft_engine_unrealized_pnl

# 组件健康状态
hft_engine_component_health

# 系统降级级别
hft_engine_degrade_level
```

## 故障排查

### Prometheus 无法抓取指标

```bash
# 检查 HFT Engine 是否运行
curl http://localhost:9090/metrics

# 检查 Prometheus 目标状态
curl http://localhost:9090/api/v1/targets
```

### 告警不触发

1. 检查规则语法: `promtool check rules alert_rules.yml`
2. 检查告警状态: http://localhost:9090/alerts
3. 验证表达式在 Prometheus UI 中是否返回结果

### 通知未收到

1. 检查 Alertmanager 日志
2. 验证 Alertmanager 配置: `amtool check-config alertmanager.yml`
3. 测试通知: `amtool config routes test --config.file=alertmanager.yml`

## 性能优化

### 高频率指标调整

```yaml
# 高频交易场景下
scrape_interval: 1s        # 最低 1 秒
evaluation_interval: 5s    # 规则评估间隔

# 保留策略
storage.tsdb.retention.time: 7d
storage.tsdb.retention.size: 10GB
```

### 远程存储 (可选)

```yaml
remote_write:
  - url: "http://thanos-receive:19291/api/v1/receive"
    queue_config:
      max_samples_per_send: 1000
      max_shards: 200
```

## 安全建议

1. **启用 TLS**: 使用 HTTPS 访问 Prometheus/Grafana
2. **认证授权**: 配置 Grafana 登录和 API 密钥
3. **网络隔离**: 监控系统应放在独立网络段
4. **访问控制**: 限制 Prometheus API 访问 IP
