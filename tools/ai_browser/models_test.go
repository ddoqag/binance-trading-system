package main

import (
	"testing"
)

func TestGetModels(t *testing.T) {
	models := GetModels()
	if len(models) == 0 {
		t.Fatal("Expected at least one model")
	}

	// Verify each model has required fields
	for _, model := range models {
		if model.Name == "" {
			t.Error("Model name cannot be empty")
		}
		if model.URL == "" {
			t.Errorf("Model %s URL cannot be empty", model.Name)
		}
		if model.RolePrompt == "" {
			t.Errorf("Model %s RolePrompt cannot be empty", model.Name)
		}
	}
}

func TestGetModels_DeepSeekRemoved(t *testing.T) {
	models := GetModels()
	for _, model := range models {
		if model.Name == "DeepSeek" {
			t.Error("DeepSeek should be removed from models list")
		}
	}
}

func TestGetModels_Count(t *testing.T) {
	models := GetModels()
	expectedCount := 10 // After removing DeepSeek
	if len(models) != expectedCount {
		t.Errorf("Expected %d models, got %d", expectedCount, len(models))
	}
}
