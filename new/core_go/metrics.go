package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"runtime"
	"sync"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

/*
metrics.go - Prometheus Metrics Exposure (P4-101)

Implements:
- Trading metrics (orders, fills, latency)
- Risk metrics (PnL, drawdown, margin)
- System metrics (goroutines, memory, CPU)
- Market data metrics (spread, volatility)
- Custom business metrics
*/

// MetricsConfig holds metrics configuration
type MetricsConfig struct {
	Enabled     bool
	Port        int
	Path        string
	Namespace   string
	Subsystem   string
	Labels      map[string]string
}

// DefaultMetricsConfig returns default configuration
func DefaultMetricsConfig() *MetricsConfig {
	return &MetricsConfig{
		Enabled:   true,
		Port:      9090,
		Path:      "/metrics",
		Namespace: "hft",
		Subsystem: "engine",
		Labels:    map[string]string{},
	}
}

// MetricsCollector manages all Prometheus metrics
type MetricsCollector struct {
	config *MetricsConfig
	reg    *prometheus.Registry

	// Trading metrics
	ordersTotal       prometheus.CounterVec
	ordersActive      prometheus.Gauge
	fillsTotal        prometheus.CounterVec
	fillLatency       prometheus.Histogram
	orderLatency      prometheus.Histogram
	tradeVolume       prometheus.CounterVec

	// Risk metrics
	unrealizedPnL     prometheus.GaugeVec
	realizedPnL       prometheus.GaugeVec
	dailyDrawdown     prometheus.Gauge
	maxDrawdown       prometheus.Gauge
	marginUsage       prometheus.Gauge
	leverage          prometheus.Gauge

	// Position metrics
	positionSize      prometheus.GaugeVec
	positionCount     prometheus.Gauge
	openOrdersCount   prometheus.Gauge

	// Market data metrics
	spread            prometheus.GaugeVec
	midPrice          prometheus.GaugeVec
	volatility        prometheus.GaugeVec
	orderBookDepth    prometheus.GaugeVec
	lastPrice         prometheus.GaugeVec

	// System metrics
	goroutines        prometheus.Gauge
	memoryUsage       prometheus.Gauge
	gcPauseNs         prometheus.Gauge
	cpuUsage          prometheus.Gauge

	// Connection metrics
	websocketConnected prometheus.Gauge
	apiRequestsTotal   prometheus.CounterVec
	apiErrorsTotal     prometheus.CounterVec
	apiLatency         prometheus.HistogramVec

	// Recovery metrics
	recoveryAttempts   prometheus.CounterVec
	recoverySuccess    prometheus.CounterVec
	componentHealth    prometheus.GaugeVec

	// Degradation metrics
	degradeLevel       prometheus.Gauge
	circuitBreakerState prometheus.GaugeVec

	// Model/Prediction metrics
	predictionLatency  prometheus.Histogram
	modelLoadFailures  prometheus.CounterVec
	modelInfo          prometheus.GaugeVec

	// A/B Testing metrics
	abTestRequests     prometheus.CounterVec

	// === Execution Alpha metrics (P3-003) ===
	// Fill quality: fill_price - mid_price (negative = good, we got better price)
	fillQuality        prometheus.HistogramVec
	// Adverse selection score (higher = more adverse)
	adverseSelection   prometheus.Gauge
	// Toxic flow probability
	toxicProbability   prometheus.Gauge
	// Queue survival rate = filled / submitted
	queueSurvivalRate  prometheus.Gauge
	// Queue survival rate by market regime
	queueSurvivalByRegime prometheus.GaugeVec
	// Cancel efficiency = effective cancels / requested cancels
	cancelEfficiency   prometheus.Gauge
	// Order latency in milliseconds (from request to exchange confirmation)
	orderLatencyMs    prometheus.Histogram
	// Execution Alpha (PnL from execution quality)
	executionAlpha     prometheus.Gauge
	// Cumulative Execution Alpha
	executionAlphaCumulative prometheus.Counter
	// Hazard rate distribution
	hazardRate         prometheus.Histogram
	// Queue ratio distribution
	queueRatio         prometheus.Histogram

	// Control
	server   *http.Server
	stopChan chan struct{}
	wg       sync.WaitGroup
	mu       sync.RWMutex
	running  bool
}

// NewMetricsCollector creates a new metrics collector
func NewMetricsCollector(config *MetricsConfig) *MetricsCollector {
	if config == nil {
		config = DefaultMetricsConfig()
	}

	reg := prometheus.NewRegistry()

	mc := &MetricsCollector{
		config:   config,
		reg:      reg,
		stopChan: make(chan struct{}),
	}

	// Initialize trading metrics
	mc.ordersTotal = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "orders_total",
			Help:      "Total number of orders",
		},
		[]string{"symbol", "side", "status"},
	)

	mc.ordersActive = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "orders_active",
			Help:      "Number of active orders",
		},
	)

	mc.fillsTotal = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "fills_total",
			Help:      "Total number of fills",
		},
		[]string{"symbol", "side"},
	)

	mc.fillLatency = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "fill_latency_seconds",
			Help:      "Fill latency in seconds",
			Buckets:   prometheus.DefBuckets,
		},
	)

	mc.orderLatency = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "order_latency_seconds",
			Help:      "Order placement latency in seconds",
			Buckets:   prometheus.DefBuckets,
		},
	)

	mc.tradeVolume = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "trade_volume",
			Help:      "Trade volume in base currency",
		},
		[]string{"symbol", "side"},
	)

	// Risk metrics
	mc.unrealizedPnL = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "unrealized_pnl",
			Help:      "Unrealized PnL",
		},
		[]string{"symbol"},
	)

	mc.realizedPnL = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "realized_pnl",
			Help:      "Realized PnL",
		},
		[]string{"symbol"},
	)

	mc.dailyDrawdown = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "daily_drawdown",
			Help:      "Daily drawdown percentage",
		},
	)

	mc.maxDrawdown = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "max_drawdown",
			Help:      "Maximum drawdown percentage",
		},
	)

	mc.marginUsage = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "margin_usage_ratio",
			Help:      "Margin usage ratio (0-1)",
		},
	)

	mc.leverage = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "leverage",
			Help:      "Current leverage",
		},
	)

	// Position metrics
	mc.positionSize = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "position_size",
			Help:      "Position size",
		},
		[]string{"symbol", "side"},
	)

	mc.positionCount = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "position_count",
			Help:      "Number of open positions",
		},
	)

	mc.openOrdersCount = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "open_orders_count",
			Help:      "Number of open orders",
		},
	)

	// Market data metrics
	mc.spread = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "spread",
			Help:      "Bid-ask spread",
		},
		[]string{"symbol"},
	)

	mc.midPrice = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "mid_price",
			Help:      "Mid price",
		},
		[]string{"symbol"},
	)

	mc.volatility = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "volatility",
			Help:      "Price volatility",
		},
		[]string{"symbol"},
	)

	mc.orderBookDepth = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "orderbook_depth",
			Help:      "Order book depth",
		},
		[]string{"symbol", "side"},
	)

	mc.lastPrice = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "last_price",
			Help:      "Last traded price",
		},
		[]string{"symbol"},
	)

	// System metrics
	mc.goroutines = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "goroutines",
			Help:      "Number of goroutines",
		},
	)

	mc.memoryUsage = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "memory_usage_bytes",
			Help:      "Memory usage in bytes",
		},
	)

	mc.gcPauseNs = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "gc_pause_ns",
			Help:      "GC pause time in nanoseconds",
		},
	)

	mc.cpuUsage = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "cpu_usage",
			Help:      "CPU usage percentage",
		},
	)

	// Connection metrics
	mc.websocketConnected = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "websocket_connected",
			Help:      "WebSocket connection status (1=connected, 0=disconnected)",
		},
	)

	mc.apiRequestsTotal = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "api_requests_total",
			Help:      "Total API requests",
		},
		[]string{"endpoint", "status"},
	)

	mc.apiErrorsTotal = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "api_errors_total",
			Help:      "Total API errors",
		},
		[]string{"endpoint", "error_type"},
	)

	mc.apiLatency = *promauto.With(reg).NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "api_latency_seconds",
			Help:      "API latency in seconds",
			Buckets:   prometheus.DefBuckets,
		},
		[]string{"endpoint"},
	)

	// Recovery metrics
	mc.recoveryAttempts = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "recovery_attempts_total",
			Help:      "Total recovery attempts",
		},
		[]string{"component", "strategy"},
	)

	mc.recoverySuccess = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "recovery_success_total",
			Help:      "Total successful recoveries",
		},
		[]string{"component"},
	)

	mc.componentHealth = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "component_health",
			Help:      "Component health status (0=unknown, 1=healthy, 2=degraded, 3=unhealthy, 4=failed)",
		},
		[]string{"component"},
	)

	// Degradation metrics
	mc.degradeLevel = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "degrade_level",
			Help:      "Current degradation level (0=normal, 1=cautious, 2=restricted, 3=emergency)",
		},
	)

	mc.circuitBreakerState = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "circuit_breaker_state",
			Help:      "Circuit breaker state (0=closed, 1=open, 2=half_open)",
		},
		[]string{"name"},
	)

	// Model/Prediction metrics
	mc.predictionLatency = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "prediction_latency_seconds",
			Help:      "Model prediction latency in seconds",
			Buckets:   []float64{0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05},
		},
	)

	mc.modelLoadFailures = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "model_load_failures_total",
			Help:      "Total model load failures",
		},
		[]string{"model"},
	)

	mc.modelInfo = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "model_info",
			Help:      "Model information (version, type)",
		},
		[]string{"model", "version", "type"},
	)

	// A/B Testing metrics
	mc.abTestRequests = *promauto.With(reg).NewCounterVec(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "ab_test_requests_total",
			Help:      "Total A/B test requests",
		},
		[]string{"variant"},
	)

	// === Execution Alpha metrics initialization ===

	// Fill quality: fill_price - mid_price (negative = good)
	mc.fillQuality = *promauto.With(reg).NewHistogramVec(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "execution_fill_quality",
			Help:      "Fill quality = fill_price - mid_price (bps), negative = better execution",
			Buckets:   []float64{-10, -5, -2, -1, -0.5, 0, 0.5, 1, 2, 5, 10},
		},
		[]string{"symbol", "side"},
	)

	// Adverse selection average score
	mc.adverseSelection = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "adverse_selection_score",
			Help:      "Average adverse selection score (higher = more toxic)",
		},
	)

	// Toxic flow probability
	mc.toxicProbability = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "toxic_probability",
			Help:      "Probability that current market is toxic [0, 1]",
		},
	)

	// Queue survival rate
	mc.queueSurvivalRate = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "queue_survival_rate",
			Help:      "Queue survival rate = filled_orders / submitted_orders [0, 1]",
		},
	)

	// Queue survival rate by market regime
	mc.queueSurvivalByRegime = *promauto.With(reg).NewGaugeVec(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "queue_survival_by_regime",
			Help:      "Queue survival rate grouped by market regime",
		},
		[]string{"regime"},
	)

	// Cancel efficiency
	mc.cancelEfficiency = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "cancel_efficiency",
			Help:      "Cancel efficiency = effective_cancels / requested_cancels [0, 1]",
		},
	)

	// Order latency milliseconds
	mc.orderLatencyMs = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "order_latency_ms",
			Help:      "Order latency from request to exchange confirmation (ms)",
			Buckets:   []float64{1, 5, 10, 25, 50, 100, 200, 500, 1000},
		},
	)

	// Current Execution Alpha
	mc.executionAlpha = promauto.With(reg).NewGauge(
		prometheus.GaugeOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "execution_alpha",
			Help:      "Current execution alpha (bps from execution quality)",
		},
	)

	// Cumulative Execution Alpha
	mc.executionAlphaCumulative = promauto.With(reg).NewCounter(
		prometheus.CounterOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "execution_alpha_cumulative_bps",
			Help:      "Cumulative execution alpha in basis points",
		},
	)

	// Hazard rate distribution
	mc.hazardRate = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "hazard_rate",
			Help:      "Hazard rate lambda distribution (per second)",
			Buckets:   []float64{0.1, 0.5, 1, 2, 5, 10, 20},
		},
	)

	// Queue ratio distribution
	mc.queueRatio = promauto.With(reg).NewHistogram(
		prometheus.HistogramOpts{
			Namespace: config.Namespace,
			Subsystem: config.Subsystem,
			Name:      "queue_ratio",
			Help:      "Queue ratio distribution [0, 1] (0=front, 1=back)",
			Buckets:   []float64{0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9},
		},
	)

	return mc
}

// Start starts the metrics HTTP server
func (mc *MetricsCollector) Start() error {
	if !mc.config.Enabled {
		return nil
	}

	mc.mu.Lock()
	if mc.running {
		mc.mu.Unlock()
		return nil
	}
	mc.running = true
	mc.mu.Unlock()

	mux := http.NewServeMux()
	mux.Handle(mc.config.Path, promhttp.HandlerFor(mc.reg, promhttp.HandlerOpts{}))

	mc.server = &http.Server{
		Addr:    fmt.Sprintf(":%d", mc.config.Port),
		Handler: mux,
	}

	mc.wg.Add(2)
	go mc.runServer()
	go mc.collectSystemMetrics()

	log.Printf("[Metrics] Started metrics server on port %d", mc.config.Port)
	return nil
}

// runServer runs the HTTP server
func (mc *MetricsCollector) runServer() {
	defer mc.wg.Done()
	if err := mc.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Printf("[Metrics] Server error: %v", err)
	}
}

// collectSystemMetrics periodically collects system metrics
func (mc *MetricsCollector) collectSystemMetrics() {
	defer mc.wg.Done()
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	var lastMemStats runtime.MemStats
	runtime.ReadMemStats(&lastMemStats)

	for {
		select {
		case <-ticker.C:
			mc.updateSystemMetrics(&lastMemStats)
		case <-mc.stopChan:
			return
		}
	}
}

// updateSystemMetrics updates system-related metrics
func (mc *MetricsCollector) updateSystemMetrics(lastMemStats *runtime.MemStats) {
	// Goroutines
	mc.goroutines.Set(float64(runtime.NumGoroutine()))

	// Memory
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	mc.memoryUsage.Set(float64(m.Alloc))

	// GC pause
	gcPause := m.PauseNs[(m.NumGC+255)%256]
	mc.gcPauseNs.Set(float64(gcPause))

	// Estimate CPU usage (simplified)
	// In production, use github.com/shirou/gopsutil
	mc.cpuUsage.Set(0) // Placeholder
}

// Stop stops the metrics server
func (mc *MetricsCollector) Stop() error {
	mc.mu.Lock()
	if !mc.running {
		mc.mu.Unlock()
		return nil
	}
	mc.running = false
	mc.mu.Unlock()

	close(mc.stopChan)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := mc.server.Shutdown(ctx); err != nil {
		return fmt.Errorf("server shutdown error: %w", err)
	}

	mc.wg.Wait()
	log.Println("[Metrics] Stopped")
	return nil
}

// RecordOrder records an order metric
func (mc *MetricsCollector) RecordOrder(symbol, side, status string) {
	if !mc.config.Enabled {
		return
	}
	mc.ordersTotal.WithLabelValues(symbol, side, status).Inc()
}

// RecordFill records a fill metric
func (mc *MetricsCollector) RecordFill(symbol, side string, size, latency float64) {
	if !mc.config.Enabled {
		return
	}
	mc.fillsTotal.WithLabelValues(symbol, side).Inc()
	mc.tradeVolume.WithLabelValues(symbol, side).Add(size)
	mc.fillLatency.Observe(latency)
}

// RecordOrderLatency records order placement latency
func (mc *MetricsCollector) RecordOrderLatency(latency float64) {
	if !mc.config.Enabled {
		return
	}
	mc.orderLatency.Observe(latency)
}

// SetActiveOrders sets the active orders count
func (mc *MetricsCollector) SetActiveOrders(count float64) {
	if !mc.config.Enabled {
		return
	}
	mc.ordersActive.Set(count)
}

// SetUnrealizedPnL sets unrealized PnL
func (mc *MetricsCollector) SetUnrealizedPnL(symbol string, pnl float64) {
	if !mc.config.Enabled {
		return
	}
	mc.unrealizedPnL.WithLabelValues(symbol).Set(pnl)
}

// SetRealizedPnL sets realized PnL
func (mc *MetricsCollector) SetRealizedPnL(symbol string, pnl float64) {
	if !mc.config.Enabled {
		return
	}
	mc.realizedPnL.WithLabelValues(symbol).Set(pnl)
}

// SetDailyDrawdown sets daily drawdown
func (mc *MetricsCollector) SetDailyDrawdown(drawdown float64) {
	if !mc.config.Enabled {
		return
	}
	mc.dailyDrawdown.Set(drawdown)
}

// SetMaxDrawdown sets max drawdown
func (mc *MetricsCollector) SetMaxDrawdown(drawdown float64) {
	if !mc.config.Enabled {
		return
	}
	mc.maxDrawdown.Set(drawdown)
}

// SetMarginUsage sets margin usage ratio
func (mc *MetricsCollector) SetMarginUsage(usage float64) {
	if !mc.config.Enabled {
		return
	}
	mc.marginUsage.Set(usage)
}

// SetLeverage sets current leverage
func (mc *MetricsCollector) SetLeverage(leverage float64) {
	if !mc.config.Enabled {
		return
	}
	mc.leverage.Set(leverage)
}

// SetPositionSize sets position size
func (mc *MetricsCollector) SetPositionSize(symbol, side string, size float64) {
	if !mc.config.Enabled {
		return
	}
	mc.positionSize.WithLabelValues(symbol, side).Set(size)
}

// SetPositionCount sets position count
func (mc *MetricsCollector) SetPositionCount(count float64) {
	if !mc.config.Enabled {
		return
	}
	mc.positionCount.Set(count)
}

// SetOpenOrdersCount sets open orders count
func (mc *MetricsCollector) SetOpenOrdersCount(count float64) {
	if !mc.config.Enabled {
		return
	}
	mc.openOrdersCount.Set(count)
}

// SetSpread sets bid-ask spread
func (mc *MetricsCollector) SetSpread(symbol string, spread float64) {
	if !mc.config.Enabled {
		return
	}
	mc.spread.WithLabelValues(symbol).Set(spread)
}

// SetMidPrice sets mid price
func (mc *MetricsCollector) SetMidPrice(symbol string, price float64) {
	if !mc.config.Enabled {
		return
	}
	mc.midPrice.WithLabelValues(symbol).Set(price)
}

// SetVolatility sets volatility
func (mc *MetricsCollector) SetVolatility(symbol string, vol float64) {
	if !mc.config.Enabled {
		return
	}
	mc.volatility.WithLabelValues(symbol).Set(vol)
}

// SetOrderBookDepth sets order book depth
func (mc *MetricsCollector) SetOrderBookDepth(symbol, side string, depth float64) {
	if !mc.config.Enabled {
		return
	}
	mc.orderBookDepth.WithLabelValues(symbol, side).Set(depth)
}

// SetLastPrice sets last price
func (mc *MetricsCollector) SetLastPrice(symbol string, price float64) {
	if !mc.config.Enabled {
		return
	}
	mc.lastPrice.WithLabelValues(symbol).Set(price)
}

// SetWebSocketConnected sets WebSocket connection status
func (mc *MetricsCollector) SetWebSocketConnected(connected bool) {
	if !mc.config.Enabled {
		return
	}
	if connected {
		mc.websocketConnected.Set(1)
	} else {
		mc.websocketConnected.Set(0)
	}
}

// RecordAPIRequest records an API request
func (mc *MetricsCollector) RecordAPIRequest(endpoint, status string) {
	if !mc.config.Enabled {
		return
	}
	mc.apiRequestsTotal.WithLabelValues(endpoint, status).Inc()
}

// RecordAPIError records an API error
func (mc *MetricsCollector) RecordAPIError(endpoint, errorType string) {
	if !mc.config.Enabled {
		return
	}
	mc.apiErrorsTotal.WithLabelValues(endpoint, errorType).Inc()
}

// RecordAPILatency records API latency
func (mc *MetricsCollector) RecordAPILatency(endpoint string, latency float64) {
	if !mc.config.Enabled {
		return
	}
	mc.apiLatency.WithLabelValues(endpoint).Observe(latency)
}

// RecordRecoveryAttempt records a recovery attempt
func (mc *MetricsCollector) RecordRecoveryAttempt(component, strategy string) {
	if !mc.config.Enabled {
		return
	}
	mc.recoveryAttempts.WithLabelValues(component, strategy).Inc()
}

// RecordRecoverySuccess records a successful recovery
func (mc *MetricsCollector) RecordRecoverySuccess(component string) {
	if !mc.config.Enabled {
		return
	}
	mc.recoverySuccess.WithLabelValues(component).Inc()
}

// SetComponentHealth sets component health status
func (mc *MetricsCollector) SetComponentHealth(component string, health HealthStatus) {
	if !mc.config.Enabled {
		return
	}
	mc.componentHealth.WithLabelValues(component).Set(float64(health))
}

// SetDegradeLevel sets degradation level
func (mc *MetricsCollector) SetDegradeLevel(level DegradeLevel) {
	if !mc.config.Enabled {
		return
	}
	mc.degradeLevel.Set(float64(level))
}

// SetCircuitBreakerState sets circuit breaker state
func (mc *MetricsCollector) SetCircuitBreakerState(name string, state BreakerState) {
	if !mc.config.Enabled {
		return
	}
	mc.circuitBreakerState.WithLabelValues(name).Set(float64(state))
}

// GetRegistry returns the Prometheus registry
func (mc *MetricsCollector) GetRegistry() *prometheus.Registry {
	return mc.reg
}

// IsRunning returns true if metrics server is running
func (mc *MetricsCollector) IsRunning() bool {
	mc.mu.RLock()
	defer mc.mu.RUnlock()
	return mc.running
}

// RecordPredictionLatency records model prediction latency
func (mc *MetricsCollector) RecordPredictionLatency(latency float64) {
	if !mc.config.Enabled {
		return
	}
	mc.predictionLatency.Observe(latency)
}

// RecordModelLoadFailure records a model load failure
func (mc *MetricsCollector) RecordModelLoadFailure(model string) {
	if !mc.config.Enabled {
		return
	}
	mc.modelLoadFailures.WithLabelValues(model).Inc()
}

// SetModelInfo sets model information
func (mc *MetricsCollector) SetModelInfo(model, version, modelType string) {
	if !mc.config.Enabled {
		return
	}
	mc.modelInfo.WithLabelValues(model, version, modelType).Set(1)
}

// RecordABTestRequest records an A/B test request
func (mc *MetricsCollector) RecordABTestRequest(variant string) {
	if !mc.config.Enabled {
		return
	}
	mc.abTestRequests.WithLabelValues(variant).Inc()
}

// === Execution Alpha recording methods (P3-003) ===

// RecordFillQuality records fill quality = fill_price - mid_price (in bps)
func (mc *MetricsCollector) RecordFillQuality(symbol, side string, fillPriceBps float64) {
	if !mc.config.Enabled {
		return
	}
	mc.fillQuality.WithLabelValues(symbol, side).Observe(fillPriceBps)
}

// SetAdverseSelection sets the current average adverse selection score
func (mc *MetricsCollector) SetAdverseSelection(score float64) {
	if !mc.config.Enabled {
		return
	}
	mc.adverseSelection.Set(score)
}

// SetToxicProbability sets the current toxic flow probability
func (mc *MetricsCollector) SetToxicProbability(prob float64) {
	if !mc.config.Enabled {
		return
	}
	mc.toxicProbability.Set(prob)
}

// SetQueueSurvivalRate sets the queue survival rate
func (mc *MetricsCollector) SetQueueSurvivalRate(rate float64) {
	if !mc.config.Enabled {
		return
	}
	mc.queueSurvivalRate.Set(rate)
}

// SetQueueSurvivalByRegime sets queue survival rate for a specific market regime
func (mc *MetricsCollector) SetQueueSurvivalByRegime(regime string, rate float64) {
	if !mc.config.Enabled {
		return
	}
	mc.queueSurvivalByRegime.WithLabelValues(regime).Set(rate)
}

// SetCancelEfficiency sets the cancel efficiency
func (mc *MetricsCollector) SetCancelEfficiency(efficiency float64) {
	if !mc.config.Enabled {
		return
	}
	mc.cancelEfficiency.Set(efficiency)
}

// RecordOrderLatencyMs records order latency in milliseconds
func (mc *MetricsCollector) RecordOrderLatencyMs(latencyMs float64) {
	if !mc.config.Enabled {
		return
	}
	mc.orderLatencyMs.Observe(latencyMs)
}

// SetExecutionAlpha sets current execution alpha in bps
func (mc *MetricsCollector) SetExecutionAlpha(alphaBps float64) {
	if !mc.config.Enabled {
		return
	}
	mc.executionAlpha.Set(alphaBps)
}

// AddExecutionAlpha adds to cumulative execution alpha in bps
func (mc *MetricsCollector) AddExecutionAlpha(alphaBps float64) {
	if !mc.config.Enabled {
		return
	}
	mc.executionAlphaCumulative.Add(alphaBps)
}

// ObserveHazardRate observes a hazard rate value
func (mc *MetricsCollector) ObserveHazardRate(lambda float64) {
	if !mc.config.Enabled {
		return
	}
	mc.hazardRate.Observe(lambda)
}

// ObserveQueueRatio observes a queue ratio value
func (mc *MetricsCollector) ObserveQueueRatio(ratio float64) {
	if !mc.config.Enabled {
		return
	}
	mc.queueRatio.Observe(ratio)
}
