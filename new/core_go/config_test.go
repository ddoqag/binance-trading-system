package main

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestConfigManager_SetDefault tests default value setting
func TestConfigManager_SetDefault(t *testing.T) {
	cm := NewConfigManager("TEST")

	cm.SetDefault("key1", "value1")
	cm.SetDefault("key2", 42)

	if cm.GetString("key1") != "value1" {
		t.Errorf("Expected key1=value1, got %v", cm.Get("key1"))
	}

	if cm.GetInt("key2") != 42 {
		t.Errorf("Expected key2=42, got %v", cm.Get("key2"))
	}
}

// TestConfigManager_SetAndGet tests setting and getting values
func TestConfigManager_SetAndGet(t *testing.T) {
	cm := NewConfigManager("TEST")

	// Test string
	cm.Set("string_key", "hello")
	if cm.GetString("string_key") != "hello" {
		t.Errorf("Expected string_key=hello, got %v", cm.GetString("string_key"))
	}

	// Test int
	cm.Set("int_key", 100)
	if cm.GetInt("int_key") != 100 {
		t.Errorf("Expected int_key=100, got %v", cm.GetInt("int_key"))
	}

	// Test float64
	cm.Set("float_key", 3.14)
	if cm.GetFloat64("float_key") != 3.14 {
		t.Errorf("Expected float_key=3.14, got %v", cm.GetFloat64("float_key"))
	}

	// Test bool
	cm.Set("bool_key", true)
	if !cm.GetBool("bool_key") {
		t.Errorf("Expected bool_key=true, got %v", cm.GetBool("bool_key"))
	}

	// Test duration
	cm.Set("duration_key", "5s")
	if cm.GetDuration("duration_key") != 5*time.Second {
		t.Errorf("Expected duration_key=5s, got %v", cm.GetDuration("duration_key"))
	}
}

// TestConfigManager_EnvironmentOverride tests environment variable override
func TestConfigManager_EnvironmentOverride(t *testing.T) {
	cm := NewConfigManager("TESTHFT")
	cm.SetDefault("symbol", "BTCUSDT")

	// Set default first
	if cm.GetString("symbol") != "BTCUSDT" {
		t.Errorf("Expected default symbol=BTCUSDT, got %v", cm.GetString("symbol"))
	}

	// Set environment variable
	os.Setenv("TESTHFT_SYMBOL", "ETHUSDT")
	defer os.Unsetenv("TESTHFT_SYMBOL")

	// Create new config manager to pick up env var
	cm2 := NewConfigManager("TESTHFT")
	cm2.SetDefault("symbol", "BTCUSDT")
	cm2.LoadFromEnv()

	if cm2.GetString("symbol") != "ETHUSDT" {
		t.Errorf("Expected env override symbol=ETHUSDT, got %v", cm2.GetString("symbol"))
	}
}

// TestConfigManager_RuntimeOverride tests runtime override priority
func TestConfigManager_RuntimeOverride(t *testing.T) {
	cm := NewConfigManager("TEST")

	// Set default
	cm.SetDefault("key", "default")
	if cm.GetString("key") != "default" {
		t.Errorf("Expected default value, got %v", cm.GetString("key"))
	}

	// Set runtime value (highest priority)
	cm.Set("key", "runtime")
	if cm.GetString("key") != "runtime" {
		t.Errorf("Expected runtime override, got %v", cm.GetString("key"))
	}
}

// TestConfigManager_LoadFromFile tests loading configuration from file
func TestConfigManager_LoadFromFile(t *testing.T) {
	// Create temp config file
	tempDir := t.TempDir()
	configPath := filepath.Join(tempDir, "config.json")

	configContent := `{
  "engine": {
    "symbol": "BTCUSDT",
    "heartbeat_ms": 200
  },
  "position": {
    "max_position": 2.0
  }
}`

	if err := os.WriteFile(configPath, []byte(configContent), 0644); err != nil {
		t.Fatalf("Failed to write test config: %v", err)
	}

	cm := NewConfigManager("TEST")
	cm.SetDefault("engine.symbol", "ETHUSDT")
	cm.SetDefault("engine.heartbeat_ms", 100)

	if err := cm.LoadFromFile(configPath); err != nil {
		t.Fatalf("Failed to load config: %v", err)
	}

	// File values should override defaults
	if cm.GetString("engine.symbol") != "BTCUSDT" {
		t.Errorf("Expected symbol=BTCUSDT from file, got %v", cm.GetString("engine.symbol"))
	}

	if cm.GetInt("engine.heartbeat_ms") != 200 {
		t.Errorf("Expected heartbeat_ms=200 from file, got %v", cm.GetInt("engine.heartbeat_ms"))
	}
}

// TestConfigManager_SaveToFile tests saving configuration to file
func TestConfigManager_SaveToFile(t *testing.T) {
	tempDir := t.TempDir()
	configPath := filepath.Join(tempDir, "saved_config.json")

	cm := NewConfigManager("TEST")
	cm.Set("engine.symbol", "BTCUSDT")
	cm.Set("engine.heartbeat_ms", 150)
	cm.Set("position.max_position", 1.5)

	if err := cm.SaveToFile(configPath); err != nil {
		t.Fatalf("Failed to save config: %v", err)
	}

	// Verify file exists
	if _, err := os.Stat(configPath); os.IsNotExist(err) {
		t.Error("Config file was not created")
	}

	// Load and verify
	cm2 := NewConfigManager("TEST")
	if err := cm2.LoadFromFile(configPath); err != nil {
		t.Fatalf("Failed to load saved config: %v", err)
	}

	if cm2.GetString("engine.symbol") != "BTCUSDT" {
		t.Errorf("Expected symbol=BTCUSDT after load, got %v", cm2.GetString("engine.symbol"))
	}
}

// TestConfigManager_Validation tests configuration validation
func TestConfigManager_Validation(t *testing.T) {
	cm := NewConfigManager("TEST")

	// Register validator
	cm.RegisterValidator("max_position", func(v interface{}) error {
		if val, ok := v.(float64); ok && val > 0 {
			return nil
		}
		if val, ok := v.(int); ok && val > 0 {
			return nil
		}
		return fmt.Errorf("max_position must be positive")
	})

	// Valid value should succeed
	if err := cm.Set("max_position", 1.0); err != nil {
		t.Errorf("Expected valid value to succeed, got: %v", err)
	}

	// Invalid value should fail
	if err := cm.Set("max_position", -1.0); err == nil {
		t.Error("Expected validation to fail for negative value")
	}
}

// TestConfigManager_OnChange tests change notification
func TestConfigManager_OnChange(t *testing.T) {
	cm := NewConfigManager("TEST")

	var changed bool
	var changedKey string
	var oldVal, newVal interface{}

	cm.OnChange(func(key string, old, new interface{}) {
		changed = true
		changedKey = key
		oldVal = old
		newVal = new
	})

	cm.SetDefault("watch_key", "initial")
	cm.Set("watch_key", "updated")

	if !changed {
		t.Error("Change callback was not called")
	}

	if changedKey != "watch_key" {
		t.Errorf("Expected changed key=watch_key, got %v", changedKey)
	}

	if oldVal != "initial" {
		t.Errorf("Expected oldVal=initial, got %v", oldVal)
	}

	if newVal != "updated" {
		t.Errorf("Expected newVal=updated, got %v", newVal)
	}
}

// TestConfigManager_GetStringSlice tests string slice parsing
func TestConfigManager_GetStringSlice(t *testing.T) {
	cm := NewConfigManager("TEST")

	// Test slice value
	cm.Set("slice_key", []string{"a", "b", "c"})
	slice := cm.GetStringSlice("slice_key")
	if len(slice) != 3 || slice[0] != "a" || slice[1] != "b" || slice[2] != "c" {
		t.Errorf("Expected [a b c], got %v", slice)
	}

	// Test comma-separated string
	cm.Set("csv_key", "x, y, z")
	csv := cm.GetStringSlice("csv_key")
	if len(csv) != 3 || csv[0] != "x" || csv[1] != "y" || csv[2] != "z" {
		t.Errorf("Expected [x y z], got %v", csv)
	}

	// Test interface slice
	cm.Set("iface_key", []interface{}{"1", "2", "3"})
	iface := cm.GetStringSlice("iface_key")
	if len(iface) != 3 {
		t.Errorf("Expected length 3, got %v", len(iface))
	}
}

// TestConfigManager_FlattenMap tests map flattening
func TestConfigManager_FlattenMap(t *testing.T) {
	nested := map[string]interface{}{
		"level1": map[string]interface{}{
			"level2": map[string]interface{}{
				"key": "value",
			},
		},
	}

	flat := flattenMap(nested, "")

	if val, exists := flat["level1.level2.key"]; !exists || val != "value" {
		t.Errorf("Expected flattened key level1.level2.key=value, got %v", flat)
	}
}

// TestConfigManager_UnflattenMap tests map unflattening
func TestConfigManager_UnflattenMap(t *testing.T) {
	flat := map[string]interface{}{
		"a.b.c": 1,
		"a.b.d": 2,
		"a.e":   3,
	}

	nested := unflattenMap(flat)

	// Check nested structure
	if a, ok := nested["a"].(map[string]interface{}); !ok {
		t.Error("Expected nested map at 'a'")
	} else if b, ok := a["b"].(map[string]interface{}); !ok {
		t.Error("Expected nested map at 'a.b'")
	} else if c, ok := b["c"].(int); !ok || c != 1 {
		t.Errorf("Expected a.b.c=1, got %v", c)
	}
}

// TestGetGlobalConfig tests singleton pattern
func TestGetGlobalConfig(t *testing.T) {
	cm1 := GetGlobalConfig()
	cm2 := GetGlobalConfig()

	if cm1 != cm2 {
		t.Error("GetGlobalConfig should return the same instance")
	}
}

// TestHFTConfig_EngineConfig tests HFT config wrapper
func TestHFTConfig_EngineConfig(t *testing.T) {
	cm := NewConfigManager("TEST")
	InitDefaultConfig(cm)

	hft := NewHFTConfig(cm)
	cfg := hft.EngineConfig()

	if cfg.Symbol != "BTCUSDT" {
		t.Errorf("Expected symbol=BTCUSDT, got %v", cfg.Symbol)
	}

	if cfg.MaxPosition != 1.0 {
		t.Errorf("Expected max_position=1.0, got %v", cfg.MaxPosition)
	}

	if cfg.PaperTrading != true {
		t.Errorf("Expected paper_trading=true, got %v", cfg.PaperTrading)
	}
}

// TestHFTConfig_RetryPolicy tests retry policy config
func TestHFTConfig_RetryPolicy(t *testing.T) {
	cm := NewConfigManager("TEST")
	InitDefaultConfig(cm)

	// Override defaults
	cm.Set("retry.max_retries", 5)
	cm.Set("retry.initial_delay_ms", 200)

	hft := NewHFTConfig(cm)
	policy := hft.RetryPolicy()

	if policy.MaxRetries != 5 {
		t.Errorf("Expected max_retries=5, got %v", policy.MaxRetries)
	}

	if policy.InitialDelay != 200*time.Millisecond {
		t.Errorf("Expected initial_delay=200ms, got %v", policy.InitialDelay)
	}
}

// TestHFTConfig_ReconnectConfig tests reconnect config
func TestHFTConfig_ReconnectConfig(t *testing.T) {
	cm := NewConfigManager("TEST")
	InitDefaultConfig(cm)

	hft := NewHFTConfig(cm)
	cfg := hft.ReconnectConfig()

	if cfg.InitialDelay != 1*time.Second {
		t.Errorf("Expected initial_delay=1s, got %v", cfg.InitialDelay)
	}

	if cfg.MaxAttempts != 10 {
		t.Errorf("Expected max_attempts=10, got %v", cfg.MaxAttempts)
	}
}

// TestInitDefaultConfig tests default configuration initialization
func TestInitDefaultConfig(t *testing.T) {
	cm := NewConfigManager("TEST")
	InitDefaultConfig(cm)

	// Verify some defaults
	tests := []struct {
		key      string
		expected interface{}
	}{
		{"engine.symbol", "BTCUSDT"},
		{"engine.paper_trading", true},
		{"position.max_position", 1.0},
		{"retry.max_retries", 3},
		{"circuit_breaker.failure_threshold", 5},
	}

	for _, tc := range tests {
		val := cm.Get(tc.key)
		if val != tc.expected {
			t.Errorf("Default %s: expected %v, got %v", tc.key, tc.expected, val)
		}
	}
}

// TestConfigManager_ConcurrentAccess tests thread safety
func TestConfigManager_ConcurrentAccess(t *testing.T) {
	cm := NewConfigManager("TEST")
	cm.SetDefault("counter", 0)

	done := make(chan bool, 10)

	// Start multiple goroutines
	for i := 0; i < 10; i++ {
		go func(id int) {
			for j := 0; j < 100; j++ {
				cm.Set("counter", id*100+j)
				cm.GetInt("counter")
			}
			done <- true
		}(i)
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}

	// If we get here without deadlock or panic, concurrent access is safe
}

// TestConfigManager_ParseEnvValue tests environment variable parsing
func TestConfigManager_ParseEnvValue(t *testing.T) {
	cm := NewConfigManager("TEST")

	tests := []struct {
		input    string
		expected interface{}
	}{
		{"true", true},
		{"false", false},
		{"123", 123},
		{"3.14", 3.14},
		{"hello", "hello"},
	}

	for _, tc := range tests {
		result := cm.parseEnvValue(tc.input)
		if result != tc.expected {
			t.Errorf("parseEnvValue(%s): expected %v (%T), got %v (%T)",
				tc.input, tc.expected, tc.expected, result, result)
		}
	}
}

// TestConfigManager_GetAll tests getting all configuration
func TestConfigManager_GetAll(t *testing.T) {
	cm := NewConfigManager("TEST")
	cm.SetDefault("key1", "default1")
	cm.Set("key2", "value2")

	all := cm.GetAll()

	if all["key1"] != "default1" {
		t.Errorf("Expected key1=default1 in GetAll, got %v", all["key1"])
	}

	if all["key2"] != "value2" {
		t.Errorf("Expected key2=value2 in GetAll, got %v", all["key2"])
	}
}
