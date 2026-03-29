package main

import (
	"os"
	"strings"
	"testing"
)

func TestDefaultConfig(t *testing.T) {
	config := DefaultConfig()
	if config == nil {
		t.Fatal("Expected non-nil config")
	}
	if config.Question == "" {
		t.Error("Expected default question to be non-empty")
	}
	if !config.IncludeRolePrompts {
		t.Error("Expected IncludeRolePrompts to be true by default")
	}
	if config.ResponseWaitTime != 60 {
		t.Errorf("Expected ResponseWaitTime 60, got %d", config.ResponseWaitTime)
	}
	if config.CustomPrompts == nil {
		t.Error("Expected CustomPrompts to be initialized")
	}
}

func TestSaveAndLoadConfig(t *testing.T) {
	// Create a temporary file
	tempFile, err := os.CreateTemp("", "test-config-*.json")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	tempPath := tempFile.Name()
	tempFile.Close()
	defer os.Remove(tempPath)

	// Create and save config
	original := DefaultConfig()
	original.Question = "Test question"
	original.ResponseWaitTime = 120

	if err := original.SaveConfig(tempPath); err != nil {
		t.Fatalf("Failed to save config: %v", err)
	}

	// Load config
	loaded, err := LoadConfig(tempPath)
	if err != nil {
		t.Fatalf("Failed to load config: %v", err)
	}

	if loaded.Question != original.Question {
		t.Errorf("Question mismatch: got %q, want %q", loaded.Question, original.Question)
	}
	if loaded.ResponseWaitTime != original.ResponseWaitTime {
		t.Errorf("ResponseWaitTime mismatch: got %d, want %d", loaded.ResponseWaitTime, original.ResponseWaitTime)
	}
}

func TestLoadConfig_NonExistentFile(t *testing.T) {
	config, err := LoadConfig("non-existent-file-12345.json")
	if err != nil {
		t.Fatalf("Expected no error for non-existent file, got %v", err)
	}
	if config == nil {
		t.Fatal("Expected default config for non-existent file")
	}
}

func TestLoadConfig_InvalidJSON(t *testing.T) {
	// Create a file with invalid JSON
	tempFile, err := os.CreateTemp("", "invalid-json-*.json")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	tempPath := tempFile.Name()
	defer os.Remove(tempPath)

	// Write invalid JSON
	if _, err := tempFile.WriteString("this is not valid JSON"); err != nil {
		t.Fatalf("Failed to write invalid JSON: %v", err)
	}
	tempFile.Close()

	// Try to load it
	config, err := LoadConfig(tempPath)
	if err == nil {
		t.Error("Expected error for invalid JSON, got nil")
	}
	if config != nil {
		t.Error("Expected nil config for invalid JSON")
	}
}

func TestSaveConfig_ReadOnlyFile(t *testing.T) {
	// Skip on Windows - readonly permissions work differently
	if strings.HasSuffix(os.Getenv("OS"), "Windows_NT") {
		t.Skip("Skipping on Windows - readonly permissions work differently")
	}

	// Create a temp file and make it readonly
	tempFile, err := os.CreateTemp("", "readonly-*.json")
	if err != nil {
		t.Fatalf("Failed to create temp file: %v", err)
	}
	tempPath := tempFile.Name()
	tempFile.Close()
	defer os.Remove(tempPath)

	if err := os.Chmod(tempPath, 0444); err != nil {
		t.Fatalf("Failed to make file readonly: %v", err)
	}

	// Try to save config
	config := DefaultConfig()
	err = config.SaveConfig(tempPath)
	if err == nil {
		t.Error("Expected error saving to readonly file, got nil")
	}
}

func TestGetPromptForModel(t *testing.T) {
	models := GetModels()
	if len(models) == 0 {
		t.Skip("No models available")
	}

	testModel := models[0]

	tests := []struct {
		name           string
		config         *ConversationConfig
		expectedLength int
		checkRole      bool
	}{
		{
			name: "With role prompt",
			config: &ConversationConfig{
				Question:          "Test question",
				IncludeRolePrompts: true,
				CustomPrompts:      make(map[string]string),
			},
			expectedLength: len(testModel.RolePrompt) + len("Test question") + 2,
			checkRole:      true,
		},
		{
			name: "Without role prompt",
			config: &ConversationConfig{
				Question:          "Test question",
				IncludeRolePrompts: false,
				CustomPrompts:      make(map[string]string),
			},
			expectedLength: len("Test question"),
			checkRole:      false,
		},
		{
			name: "With custom prompt",
			config: &ConversationConfig{
				Question:          "Test question",
				IncludeRolePrompts: true,
				CustomPrompts: map[string]string{
					testModel.Name: "Custom role prompt",
				},
			},
			expectedLength: len("Custom role prompt") + len("Test question") + 2,
			checkRole:      false,
		},
		{
			name: "With custom prompt for other model",
			config: &ConversationConfig{
				Question:          "Test question",
				IncludeRolePrompts: true,
				CustomPrompts: map[string]string{
					"OtherModel": "Custom role prompt",
				},
			},
			expectedLength: len(testModel.RolePrompt) + len("Test question") + 2,
			checkRole:      true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			prompt := tt.config.GetPromptForModel(testModel)
			if len(prompt) < tt.expectedLength {
				t.Errorf("Prompt too short: got %d chars, want at least %d", len(prompt), tt.expectedLength)
			}
			if tt.checkRole {
				if !strings.Contains(prompt, testModel.RolePrompt) {
					t.Error("Expected role prompt to be included")
				}
			}
			if !strings.Contains(prompt, "Test question") {
				t.Error("Expected question to be included")
			}
		})
	}
}
