package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// TestNewModelManager tests creation of model manager
func TestNewModelManager(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	if mm.config == nil {
		t.Error("Config should not be nil")
	}

	if len(mm.models) != 0 {
		t.Error("Should have no models initially")
	}

	t.Logf("✓ ModelManager creation test passed")
}

// TestLoadModel tests model loading
func TestLoadModel(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	// Create a dummy model file
	modelPath := filepath.Join(tempDir, "test_model.onnx")
	dummyData := make([]byte, 1000)
	if err := os.WriteFile(modelPath, dummyData, 0644); err != nil {
		t.Fatalf("Failed to create test model: %v", err)
	}

	// Load model
	ctx := context.Background()
	if err := mm.LoadModel(ctx, "test_model", modelPath, ModelTypeDQN); err != nil {
		t.Errorf("Failed to load model: %v", err)
	}

	// Verify model loaded
	models := mm.ListModels("test_model")
	if len(models) != 1 {
		t.Errorf("Expected 1 model, got %d", len(models))
	}

	model := models[0]
	if model.Name != "test_model" {
		t.Errorf("Expected name 'test_model', got '%s'", model.Name)
	}

	if model.Type != ModelTypeDQN {
		t.Errorf("Expected type DQN, got %v", model.Type)
	}

	if model.Size != 1000 {
		t.Errorf("Expected size 1000, got %d", model.Size)
	}

	t.Logf("✓ Model load test passed")
}

// TestSwitchModel tests model switching
func TestSwitchModel(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	// Load two models
	ctx := context.Background()

	model1Path := filepath.Join(tempDir, "model1.onnx")
	os.WriteFile(model1Path, []byte("model1_data"), 0644)
	mm.LoadModel(ctx, "mymodel", model1Path, ModelTypeDQN)

	model2Path := filepath.Join(tempDir, "model2.onnx")
	os.WriteFile(model2Path, []byte("model2_data"), 0644)
	mm.LoadModel(ctx, "mymodel", model2Path, ModelTypeDQN)

	// Get versions
	models := mm.ListModels("mymodel")
	if len(models) != 2 {
		t.Fatalf("Expected 2 models, got %d", len(models))
	}

	// Switch to second model
	if err := mm.SwitchModel(models[1].ID); err != nil {
		t.Errorf("Failed to switch model: %v", err)
	}

	current := mm.GetCurrentModel()
	if current == nil {
		t.Error("Current model should not be nil")
	} else if current.ID != models[1].ID {
		t.Error("Switched to wrong model")
	}

	t.Logf("✓ Model switch test passed")
}

// TestUnloadModel tests model unloading
func TestUnloadModel(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	// Load model
	ctx := context.Background()
	modelPath := filepath.Join(tempDir, "test.onnx")
	os.WriteFile(modelPath, []byte("data"), 0644)
	mm.LoadModel(ctx, "test", modelPath, ModelTypePPO)

	models := mm.ListModels("test")
	if len(models) != 1 {
		t.Fatalf("Expected 1 model")
	}

	// Unload
	if err := mm.UnloadModel(models[0].ID); err != nil {
		t.Errorf("Failed to unload model: %v", err)
	}

	// Verify unloaded
	models = mm.ListModels("test")
	if len(models) != 0 {
		t.Errorf("Expected 0 models after unload, got %d", len(models))
	}

	t.Logf("✓ Model unload test passed")
}

// TestABTest tests A/B testing functionality
func TestABTest(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	// Load two models
	ctx := context.Background()

	modelAPath := filepath.Join(tempDir, "model_a.onnx")
	os.WriteFile(modelAPath, []byte("model_a"), 0644)
	mm.LoadModel(ctx, "model_a", modelAPath, ModelTypeSAC)

	modelBPath := filepath.Join(tempDir, "model_b.onnx")
	os.WriteFile(modelBPath, []byte("model_b"), 0644)
	mm.LoadModel(ctx, "model_b", modelBPath, ModelTypeSAC)

	modelsA := mm.ListModels("model_a")
	modelsB := mm.ListModels("model_b")

	// Start A/B test
	abConfig := &ABTestConfig{
		Enabled:     true,
		VariantA:    modelsA[0].ID,
		VariantB:    modelsB[0].ID,
		SplitRatio:  0.5,
		StartTime:   time.Now(),
		Description: "Test A/B test",
	}

	if err := mm.StartABTest(abConfig); err != nil {
		t.Errorf("Failed to start A/B test: %v", err)
	}

	// Verify A/B test is active
	if mm.GetABTestConfig() == nil {
		t.Error("A/B test config should not be nil")
	}

	// Test model selection
	for i := 0; i < 100; i++ {
		_, isAB := mm.SelectModelForPrediction()
		if !isAB {
			t.Error("Should be in A/B test mode")
		}
	}

	// Get results
	results := mm.GetABTestResults()
	if len(results) != 2 {
		t.Errorf("Expected 2 A/B test results, got %d", len(results))
	}

	// Stop A/B test
	mm.StopABTest()
	if mm.GetABTestConfig() != nil {
		t.Error("A/B test should be stopped")
	}

	t.Logf("✓ A/B test passed")
}

// TestRecordPrediction tests prediction metrics recording
func TestRecordPrediction(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	// Load model
	ctx := context.Background()
	modelPath := filepath.Join(tempDir, "test.onnx")
	os.WriteFile(modelPath, []byte("data"), 0644)
	mm.LoadModel(ctx, "test", modelPath, ModelTypeDQN)

	model := mm.ListModels("test")[0]

	// Record predictions
	for i := 0; i < 10; i++ {
		mm.RecordPrediction(model.ID, 10*time.Millisecond, nil)
	}
	mm.RecordPrediction(model.ID, 20*time.Millisecond, errTest)

	// Verify metrics
	if model.Performance.TotalPredictions != 11 {
		t.Errorf("Expected 11 predictions, got %d", model.Performance.TotalPredictions)
	}

	if model.Performance.Errors != 1 {
		t.Errorf("Expected 1 error, got %d", model.Performance.Errors)
	}

	t.Logf("✓ Prediction recording test passed")
}

// TestCallbacks tests callback functionality
func TestCallbacks(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	var loadCalled, unloadCalled bool
	mm.SetCallbacks(
		func(m *ModelVersion) { loadCalled = true },
		func(m *ModelVersion) { unloadCalled = true },
		nil,
	)

	// Load model
	ctx := context.Background()
	modelPath := filepath.Join(tempDir, "test.onnx")
	os.WriteFile(modelPath, []byte("data"), 0644)
	mm.LoadModel(ctx, "test", modelPath, ModelTypeDQN)

	if !loadCalled {
		t.Error("Load callback should have been called")
	}

	// Unload model
	model := mm.ListModels("test")[0]
	mm.UnloadModel(model.ID)

	if !unloadCalled {
		t.Error("Unload callback should have been called")
	}

	t.Logf("✓ Callbacks test passed")
}

// TestGetStats tests statistics retrieval
func TestGetStats(t *testing.T) {
	tempDir := t.TempDir()

	config := DefaultModelConfig()
	config.ModelDir = tempDir
	config.WatchEnabled = false

	mm, err := NewModelManager(config)
	if err != nil {
		t.Fatalf("Failed to create ModelManager: %v", err)
	}
	defer mm.Stop()

	stats := mm.GetStats()

	if _, ok := stats["total_models"]; !ok {
		t.Error("Stats should include total_models")
	}

	if _, ok := stats["active_models"]; !ok {
		t.Error("Stats should include active_models")
	}

	t.Logf("✓ Stats test passed")
}

// TestDefaultModelConfig tests default configuration
func TestDefaultModelConfig(t *testing.T) {
	config := DefaultModelConfig()

	if config.ModelDir != "./models" {
		t.Errorf("Expected default ModelDir './models', got '%s'", config.ModelDir)
	}

	if !config.WatchEnabled {
		t.Error("WatchEnabled should be true by default")
	}

	if config.MaxVersions != 5 {
		t.Errorf("Expected MaxVersions 5, got %d", config.MaxVersions)
	}

	t.Logf("✓ Default config test passed")
}

// TestModelTypeString tests ModelType String method
func TestModelTypeString(t *testing.T) {
	tests := []struct {
		mt       ModelType
		expected string
	}{
		{ModelTypeDQN, "DQN"},
		{ModelTypePPO, "PPO"},
		{ModelTypeSAC, "SAC"},
		{ModelTypeCustom, "CUSTOM"},
		{ModelType(99), "UNKNOWN"},
	}

	for _, tt := range tests {
		if got := tt.mt.String(); got != tt.expected {
			t.Errorf("ModelType.String() = %v, want %v", got, tt.expected)
		}
	}

	t.Logf("✓ ModelType string test passed")
}

// errTest is a test error
var errTest = &testError{msg: "test error"}

type testError struct {
	msg string
}

func (e *testError) Error() string { return e.msg }
