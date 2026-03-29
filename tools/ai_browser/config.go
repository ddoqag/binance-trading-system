package main

import (
	"encoding/json"
	"os"
)

// ConversationConfig holds the conversation settings
type ConversationConfig struct {
	// Question to ask all AI models
	Question string `json:"question"`

	// Whether to include role prompts
	IncludeRolePrompts bool `json:"include_role_prompts"`

	// Custom prompts for specific models (optional override)
	CustomPrompts map[string]string `json:"custom_prompts,omitempty"`

	// Wait time for responses (seconds)
	ResponseWaitTime int `json:"response_wait_time"`
}

// DefaultConfig returns the default configuration
func DefaultConfig() *ConversationConfig {
	return &ConversationConfig{
		Question: "Explain the concept of 'Technical Debt' in software engineering. " +
			"Include: 1) Definition, 2) Common causes, 3) How to manage it, 4) When it's acceptable. " +
			"Keep your answer concise but comprehensive.",
		IncludeRolePrompts: true,
		CustomPrompts:      make(map[string]string),
		ResponseWaitTime:   60,
	}
}

// LoadConfig loads configuration from file or returns default
func LoadConfig(path string) (*ConversationConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return DefaultConfig(), nil
		}
		return nil, err
	}

	var config ConversationConfig
	if err := json.Unmarshal(data, &config); err != nil {
		return nil, err
	}

	return &config, nil
}

// SaveConfig saves configuration to file
func (c *ConversationConfig) SaveConfig(path string) error {
	data, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0644)
}

// GetPromptForModel returns the full prompt for a specific model
func (c *ConversationConfig) GetPromptForModel(model AIModel) string {
	// Check for custom prompt override
	if custom, ok := c.CustomPrompts[model.Name]; ok {
		return custom + "\n\n" + c.Question
	}

	if c.IncludeRolePrompts {
		return model.RolePrompt + "\n\n" + c.Question
	}

	return c.Question
}
