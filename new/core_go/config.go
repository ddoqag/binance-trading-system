package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"
)

/*
config.go - Configuration Management System

Features:
- Multi-source configuration (file, env, runtime)
- Hot reload support
- Configuration validation
- Default values
- Type-safe access
- Change notifications

Configuration Hierarchy (highest priority first):
1. Runtime overrides (Set)
2. Environment variables
3. Configuration file
4. Default values
*/

// ConfigManager manages all configuration for the HFT engine
type ConfigManager struct {
	mu       sync.RWMutex
	data     map[string]interface{} // From file/env
	overrides map[string]interface{} // From Set() - highest priority
	defaults map[string]interface{}
	envPrefix string
	filePath  string

	// Hot reload
	watcher    *ConfigWatcher
	onChange   []func(key string, oldVal, newVal interface{})

	// Validation
	validators map[string]func(interface{}) error
}

// NewConfigManager creates a new configuration manager
func NewConfigManager(envPrefix string) *ConfigManager {
	return &ConfigManager{
		data:       make(map[string]interface{}),
		overrides:  make(map[string]interface{}),
		defaults:   make(map[string]interface{}),
		envPrefix:  envPrefix,
		validators: make(map[string]func(interface{}) error),
		onChange:   make([]func(string, interface{}, interface{}), 0),
	}
}

// SetDefault sets a default value for a configuration key
func (cm *ConfigManager) SetDefault(key string, value interface{}) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.defaults[key] = value
}

// Set sets a configuration value (highest priority)
func (cm *ConfigManager) Set(key string, value interface{}) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	// Validate if validator exists
	if validator, exists := cm.validators[key]; exists {
		if err := validator(value); err != nil {
			return fmt.Errorf("validation failed for key %s: %w", key, err)
		}
	}

	// Get current effective value as oldVal (checking all sources in priority order)
	var oldVal interface{}
	if val, exists := cm.overrides[key]; exists {
		oldVal = val
	} else {
		// Use getUnlocked to get the current effective value
		oldVal = cm.getUnlocked(key)
	}

	cm.overrides[key] = value

	// Notify change listeners
	if !reflect.DeepEqual(oldVal, value) {
		for _, cb := range cm.onChange {
			cb(key, oldVal, value)
		}
	}

	return nil
}

// getUnlocked gets a configuration value without locking (for internal use)
func (cm *ConfigManager) getUnlocked(key string) interface{} {
	// Check environment variable
	envKey := cm.envPrefix + "_" + strings.ToUpper(strings.ReplaceAll(key, ".", "_"))
	if envVal := os.Getenv(envKey); envVal != "" {
		return cm.parseEnvValue(envVal)
	}

	// Check data (from file or env loading)
	if val, exists := cm.data[key]; exists {
		return val
	}

	// Return default
	return cm.defaults[key]
}

// Get retrieves a configuration value
func (cm *ConfigManager) Get(key string) interface{} {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	// 1. Check runtime override first (highest priority)
	if val, exists := cm.overrides[key]; exists {
		return val
	}

	// 2. Check environment variable
	envKey := cm.envPrefix + "_" + strings.ToUpper(strings.ReplaceAll(key, ".", "_"))
	if envVal := os.Getenv(envKey); envVal != "" {
		return cm.parseEnvValue(envVal)
	}

	// 3. Check data (from file or env loading)
	if val, exists := cm.data[key]; exists {
		return val
	}

	// 4. Return default (lowest priority)
	return cm.defaults[key]
}

// GetString gets a string value
func (cm *ConfigManager) GetString(key string) string {
	val := cm.Get(key)
	if val == nil {
		return ""
	}
	if s, ok := val.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", val)
}

// GetInt gets an integer value
func (cm *ConfigManager) GetInt(key string) int {
	val := cm.Get(key)
	if val == nil {
		return 0
	}
	switch v := val.(type) {
	case int:
		return v
	case int64:
		return int(v)
	case float64:
		return int(v)
	case string:
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return 0
}

// GetFloat64 gets a float64 value
func (cm *ConfigManager) GetFloat64(key string) float64 {
	val := cm.Get(key)
	if val == nil {
		return 0
	}
	switch v := val.(type) {
	case float64:
		return v
	case float32:
		return float64(v)
	case int:
		return float64(v)
	case int64:
		return float64(v)
	case string:
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			return f
		}
	}
	return 0
}

// GetBool gets a boolean value
func (cm *ConfigManager) GetBool(key string) bool {
	val := cm.Get(key)
	if val == nil {
		return false
	}
	switch v := val.(type) {
	case bool:
		return v
	case string:
		if b, err := strconv.ParseBool(v); err == nil {
			return b
		}
	}
	return false
}

// GetDuration gets a duration value
func (cm *ConfigManager) GetDuration(key string) time.Duration {
	val := cm.Get(key)
	if val == nil {
		return 0
	}
	switch v := val.(type) {
	case time.Duration:
		return v
	case string:
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	case int:
		return time.Duration(v)
	case int64:
		return time.Duration(v)
	case float64:
		return time.Duration(v)
	}
	return 0
}

// GetStringSlice gets a string slice
func (cm *ConfigManager) GetStringSlice(key string) []string {
	val := cm.Get(key)
	if val == nil {
		return nil
	}
	switch v := val.(type) {
	case []string:
		return v
	case []interface{}:
		result := make([]string, len(v))
		for i, item := range v {
			result[i] = fmt.Sprintf("%v", item)
		}
		return result
	case string:
		// Parse comma-separated values
		if v == "" {
			return nil
		}
		parts := strings.Split(v, ",")
		result := make([]string, len(parts))
		for i, p := range parts {
			result[i] = strings.TrimSpace(p)
		}
		return result
	}
	return nil
}

// LoadFromFile loads configuration from a JSON file
func (cm *ConfigManager) LoadFromFile(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("failed to read config file: %w", err)
	}

	var config map[string]interface{}
	if err := json.Unmarshal(data, &config); err != nil {
		return fmt.Errorf("failed to parse config file: %w", err)
	}

	cm.mu.Lock()
	defer cm.mu.Unlock()

	// Flatten nested structures
	flattened := flattenMap(config, "")
	for key, value := range flattened {
		// Only set if not already set (lower priority than runtime)
		if _, exists := cm.data[key]; !exists {
			cm.data[key] = value
		}
	}

	cm.filePath = path
	return nil
}

// SaveToFile saves current configuration to a JSON file
func (cm *ConfigManager) SaveToFile(path string) error {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	// Merge all configuration values: defaults <- data <- overrides
	merged := make(map[string]interface{})
	for k, v := range cm.defaults {
		merged[k] = v
	}
	for k, v := range cm.data {
		merged[k] = v
	}
	for k, v := range cm.overrides {
		merged[k] = v
	}

	// Unflatten merged data
	config := unflattenMap(merged)

	data, err := json.MarshalIndent(config, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return fmt.Errorf("failed to create config directory: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}

	return nil
}

// LoadFromEnv loads configuration from environment variables
func (cm *ConfigManager) LoadFromEnv() {
	prefix := cm.envPrefix + "_"
	for _, env := range os.Environ() {
		parts := strings.SplitN(env, "=", 2)
		if len(parts) != 2 {
			continue
		}

		key, value := parts[0], parts[1]
		if !strings.HasPrefix(key, prefix) {
			continue
		}

		// Convert HFT_SYMBOL to symbol
		configKey := strings.ToLower(strings.TrimPrefix(key, prefix))
		configKey = strings.ReplaceAll(configKey, "_", ".")

		cm.mu.Lock()
		if _, exists := cm.data[configKey]; !exists {
			cm.data[configKey] = cm.parseEnvValue(value)
		}
		cm.mu.Unlock()
	}
}

// RegisterValidator registers a validation function for a key
func (cm *ConfigManager) RegisterValidator(key string, validator func(interface{}) error) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.validators[key] = validator
}

// OnChange registers a callback for configuration changes
func (cm *ConfigManager) OnChange(callback func(key string, oldVal, newVal interface{})) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.onChange = append(cm.onChange, callback)
}

// GetAll returns all configuration values
func (cm *ConfigManager) GetAll() map[string]interface{} {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	result := make(map[string]interface{})
	for k, v := range cm.defaults {
		result[k] = v
	}
	for k, v := range cm.data {
		result[k] = v
	}
	for k, v := range cm.overrides {
		result[k] = v
	}
	return result
}

// parseEnvValue parses environment variable values
func (cm *ConfigManager) parseEnvValue(value string) interface{} {
	// Try bool
	if b, err := strconv.ParseBool(value); err == nil && (value == "true" || value == "false") {
		return b
	}

	// Try int
	if i, err := strconv.ParseInt(value, 10, 64); err == nil {
		return int(i)
	}

	// Try float
	if f, err := strconv.ParseFloat(value, 64); err == nil && strings.Contains(value, ".") {
		return f
	}

	// Return as string
	return value
}

// flattenMap flattens a nested map into a flat map with dot notation keys
func flattenMap(m map[string]interface{}, prefix string) map[string]interface{} {
	result := make(map[string]interface{})
	for k, v := range m {
		key := k
		if prefix != "" {
			key = prefix + "." + k
		}

		switch val := v.(type) {
		case map[string]interface{}:
			nested := flattenMap(val, key)
			for nk, nv := range nested {
				result[nk] = nv
			}
		default:
			result[key] = v
		}
	}
	return result
}

// unflattenMap converts a flat map with dot notation keys into a nested map
func unflattenMap(m map[string]interface{}) map[string]interface{} {
	result := make(map[string]interface{})

	for key, value := range m {
		parts := strings.Split(key, ".")
		current := result

		for i, part := range parts {
			if i == len(parts)-1 {
				current[part] = value
			} else {
				if _, exists := current[part]; !exists {
					current[part] = make(map[string]interface{})
				}
				if next, ok := current[part].(map[string]interface{}); ok {
					current = next
				}
			}
		}
	}

	return result
}

// Global configuration manager instance
var (
	globalConfig     *ConfigManager
	globalConfigOnce sync.Once
)

// GetGlobalConfig returns the global configuration manager
func GetGlobalConfig() *ConfigManager {
	globalConfigOnce.Do(func() {
		globalConfig = NewConfigManager("HFT")
		InitDefaultConfig(globalConfig)
	})
	return globalConfig
}

// InitDefaultConfig initializes default configuration values
func InitDefaultConfig(cm *ConfigManager) {
	// Engine settings
	cm.SetDefault("engine.symbol", "BTCUSDT")
	cm.SetDefault("engine.shm_path", "/tmp/hft_trading_shm")
	cm.SetDefault("engine.heartbeat_ms", 100)
	cm.SetDefault("engine.paper_trading", true)

	// Position settings
	cm.SetDefault("position.max_position", 1.0)
	cm.SetDefault("position.base_order_size", 0.01)
	cm.SetDefault("position.max_leverage", 3.0)
	cm.SetDefault("position.use_margin", false)

	// Risk settings
	cm.SetDefault("risk.max_daily_loss", 0.05)
	cm.SetDefault("risk.max_single_position", 0.2)
	cm.SetDefault("risk.max_total_position", 0.8)
	cm.SetDefault("risk.stop_loss_pct", 0.02)
	cm.SetDefault("risk.take_profit_pct", 0.05)
	cm.SetDefault("risk.trailing_stop_pct", 0.015)
	cm.SetDefault("risk.use_trailing_stop", false)
	cm.SetDefault("risk.max_slippage_pct", 0.001)
	cm.SetDefault("risk.enable_slippage_check", true)
	cm.SetDefault("risk.enable_holding_limit", false)
	cm.SetDefault("risk.max_holding_time_hours", 24)
	cm.SetDefault("risk.enable_volatility_adaption", false)
	cm.SetDefault("risk.risk_level", "balanced")
	cm.SetDefault("risk.max_orders_per_hour", 1000)
	cm.SetDefault("risk.max_orders_per_day", 5000)
	cm.SetDefault("risk.alert_cooldown_min", 5)

	// Retry settings
	cm.SetDefault("retry.max_retries", 3)
	cm.SetDefault("retry.initial_delay_ms", 500)
	cm.SetDefault("retry.max_delay_ms", 30000)
	cm.SetDefault("retry.backoff_multiplier", 2.0)

	// Circuit breaker settings
	cm.SetDefault("circuit_breaker.failure_threshold", 5)
	cm.SetDefault("circuit_breaker.recovery_timeout_ms", 30000)

	// WebSocket settings
	cm.SetDefault("websocket.initial_reconnect_delay_ms", 1000)
	cm.SetDefault("websocket.max_reconnect_delay_ms", 60000)
	cm.SetDefault("websocket.max_reconnect_attempts", 10)
	cm.SetDefault("websocket.health_check_interval_ms", 30000)
	cm.SetDefault("websocket.stale_threshold_ms", 60000)

	// WAL settings
	cm.SetDefault("wal.max_file_size_mb", 100)
	cm.SetDefault("wal.checkpoint_interval_ms", 300000)
	cm.SetDefault("wal.flush_interval_ms", 1000)

	// Rate limit settings
	cm.SetDefault("ratelimit.weight_limit", 960)
	cm.SetDefault("ratelimit.orders_per_10s", 80)

	// STP (Self-Trade Prevention) settings
	cm.SetDefault("stp.enable", true)
	cm.SetDefault("stp.mode", "REJECT")
	cm.SetDefault("stp.check_interval_ms", 100)
	cm.SetDefault("stp.max_attempts", 5)
	cm.SetDefault("stp.cooldown_ms", 60000)
	cm.SetDefault("stp.log_events", true)
	cm.SetDefault("stp.alert", true)
	cm.SetDefault("stp.price_tolerance", 0.0001)
	cm.RegisterValidator("position.max_position", func(v interface{}) error {
		if cm.toFloat64(v) <= 0 {
			return fmt.Errorf("max_position must be positive")
		}
		return nil
	})

	cm.RegisterValidator("risk.max_daily_loss", func(v interface{}) error {
		val := cm.toFloat64(v)
		if val <= 0 || val > 1 {
			return fmt.Errorf("max_daily_loss must be between 0 and 1")
		}
		return nil
	})

	cm.RegisterValidator("position.max_leverage", func(v interface{}) error {
		val := cm.toFloat64(v)
		if val < 1 || val > 125 {
			return fmt.Errorf("max_leverage must be between 1 and 125")
		}
		return nil
	})
}

// Helper function to convert interface to float64
func (cm *ConfigManager) toFloat64(v interface{}) float64 {
	switch val := v.(type) {
	case float64:
		return val
	case float32:
		return float64(val)
	case int:
		return float64(val)
	case int64:
		return float64(val)
	case string:
		if f, err := strconv.ParseFloat(val, 64); err == nil {
			return f
		}
	}
	return 0
}

// ConfigWatcher watches configuration file for changes
type ConfigWatcher struct {
	cm       *ConfigManager
	filePath string
	interval time.Duration
	stopCh   chan struct{}
	lastMod  time.Time
}

// NewConfigWatcher creates a new config file watcher
func NewConfigWatcher(cm *ConfigManager, filePath string, interval time.Duration) *ConfigWatcher {
	return &ConfigWatcher{
		cm:       cm,
		filePath: filePath,
		interval: interval,
		stopCh:   make(chan struct{}),
	}
}

// Start begins watching the configuration file
func (cw *ConfigWatcher) Start() {
	go cw.watch()
}

// Stop stops watching the configuration file
func (cw *ConfigWatcher) Stop() {
	close(cw.stopCh)
}

// watch periodically checks for file changes
func (cw *ConfigWatcher) watch() {
	ticker := time.NewTicker(cw.interval)
	defer ticker.Stop()

	for {
		select {
		case <-cw.stopCh:
			return
		case <-ticker.C:
			cw.checkAndReload()
		}
	}
}

// checkAndReload checks if file has changed and reloads if necessary
func (cw *ConfigWatcher) checkAndReload() {
	info, err := os.Stat(cw.filePath)
	if err != nil {
		return
	}

	if info.ModTime().After(cw.lastMod) {
		cw.lastMod = info.ModTime()
		cw.cm.LoadFromFile(cw.filePath)
	}
}

// HFTConfig provides type-safe access to common HFT configuration
type HFTConfig struct {
	cm *ConfigManager
}

// NewHFTConfig creates a new HFT configuration wrapper
func NewHFTConfig(cm *ConfigManager) *HFTConfig {
	return &HFTConfig{cm: cm}
}

// EngineConfig returns engine configuration
func (hc *HFTConfig) EngineConfig() *EngineConfig {
	return &EngineConfig{
		Symbol:        hc.cm.GetString("engine.symbol"),
		SHMPath:       hc.cm.GetString("engine.shm_path"),
		MaxPosition:   hc.cm.GetFloat64("position.max_position"),
		BaseOrderSize: hc.cm.GetFloat64("position.base_order_size"),
		HeartbeatMs:   hc.cm.GetInt("engine.heartbeat_ms"),
		PaperTrading:  hc.cm.GetBool("engine.paper_trading"),
		UseMargin:     hc.cm.GetBool("position.use_margin"),
		MaxLeverage:   hc.cm.GetFloat64("position.max_leverage"),
	}
}

// RetryPolicy returns retry policy configuration
func (hc *HFTConfig) RetryPolicy() *RetryPolicy {
	return &RetryPolicy{
		MaxRetries:        hc.cm.GetInt("retry.max_retries"),
		InitialDelay:      time.Duration(hc.cm.GetInt("retry.initial_delay_ms")) * time.Millisecond,
		MaxDelay:          time.Duration(hc.cm.GetInt("retry.max_delay_ms")) * time.Millisecond,
		BackoffMultiplier: hc.cm.GetFloat64("retry.backoff_multiplier"),
		JitterFactor:      0.2,
	}
}

// ReconnectConfig returns WebSocket reconnect configuration
func (hc *HFTConfig) ReconnectConfig() *ReconnectConfig {
	return &ReconnectConfig{
		InitialDelay:   time.Duration(hc.cm.GetInt("websocket.initial_reconnect_delay_ms")) * time.Millisecond,
		MaxDelay:       time.Duration(hc.cm.GetInt("websocket.max_reconnect_delay_ms")) * time.Millisecond,
		MaxAttempts:    hc.cm.GetInt("websocket.max_reconnect_attempts"),
		HealthInterval: time.Duration(hc.cm.GetInt("websocket.health_check_interval_ms")) * time.Millisecond,
		StaleThreshold: time.Duration(hc.cm.GetInt("websocket.stale_threshold_ms")) * time.Millisecond,
	}
}

// RiskConfig returns risk management configuration
func (hc *HFTConfig) RiskConfig() *RiskConfig {
	return RiskConfigFromConfigManager(hc.cm)
}

// STPConfig returns self-trade prevention configuration
func (hc *HFTConfig) STPConfig() *STPConfig {
	return STPConfigFromConfigManager(hc.cm)
}
