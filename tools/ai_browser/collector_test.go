package main

import (
	"strings"
	"testing"
	"time"
)

func TestNewResponseCollector(t *testing.T) {
	rc := NewResponseCollector()
	if rc == nil {
		t.Fatal("Expected non-nil ResponseCollector")
	}
	if rc.Responses == nil {
		t.Error("Expected Responses map to be initialized")
	}
}

func TestAddAndGetResponse(t *testing.T) {
	rc := NewResponseCollector()

	resp := &AIResponse{
		ModelName: "TestModel",
		URL:       "https://example.com",
		Question:  "Test question",
		Content:   "Test response",
		Status:    "success",
		Timestamp: time.Now(),
	}

	rc.AddResponse(resp)

	retrieved := rc.GetResponse("TestModel")
	if retrieved == nil {
		t.Fatal("Expected to retrieve added response")
	}
	if retrieved.Content != "Test response" {
		t.Errorf("Expected content 'Test response', got '%s'", retrieved.Content)
	}
}

func TestTruncate(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		maxLen   int
		expected string
	}{
		{
			name:     "Short string no truncation",
			input:    "Hello",
			maxLen:   10,
			expected: "Hello",
		},
		{
			name:     "Exact length no truncation",
			input:    "Hello",
			maxLen:   5,
			expected: "Hello",
		},
		{
			name:     "Long string truncated",
			input:    "Hello World",
			maxLen:   5,
			expected: "Hello...",
		},
		{
			name:     "Empty string",
			input:    "",
			maxLen:   10,
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := truncate(tt.input, tt.maxLen)
			if result != tt.expected {
				t.Errorf("truncate(%q, %d) = %q, want %q", tt.input, tt.maxLen, result, tt.expected)
			}
		})
	}
}

func TestCleanResponse(t *testing.T) {
	tests := []struct {
		name           string
		content        string
		question       string
		shouldContain  string
		shouldNotContain string
	}{
		{
			name:           "No question prefix",
			content:        "This is the response",
			question:       "What is your name?",
			shouldContain: "This is the response",
		},
		{
			name:           "Question at beginning",
			content:        "What is your name?This is the response",
			question:       "What is your name?",
			shouldContain: "This is the response",
		},
		{
			name:           "Question with Chinese prefix - no removal",
			content:        "请评价以下内容...Actual response here",
			question:       "请评价以下内容",
			shouldContain: "Actual response",
		},
		{
			name:           "First line is question - should try to remove",
			content:        "请评价以下内容\n\nActual response here",
			question:       "请评价以下内容",
			shouldContain: "Actual response",
		},
		{
			name:           "Empty content",
			content:        "",
			question:       "What is your name?",
			shouldContain: "",
		},
		{
			name:           "Content shorter than question",
			content:        "Short",
			question:       "What is your name?",
			shouldContain: "Short",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := cleanResponse(tt.content, tt.question)
			if tt.shouldContain != "" && !containsSubstringTest(result, tt.shouldContain) {
				t.Errorf("Expected result to contain %q, got %q", tt.shouldContain, result)
			}
			if tt.shouldNotContain != "" && containsSubstringTest(result, tt.shouldNotContain) {
				t.Errorf("Expected result NOT to contain %q, got %q", tt.shouldNotContain, result)
			}
		})
	}
}

func containsSubstringTest(s, substr string) bool {
	return strings.Contains(s, substr)
}

func TestGetSelectorsForModel(t *testing.T) {
	tests := []struct {
		name          string
		modelName     string
		expectedCount int
	}{
		{
			name:          "ChatGPT selectors",
			modelName:     "ChatGPT",
			expectedCount: 3,
		},
		{
			name:          "Claude selectors",
			modelName:     "Claude",
			expectedCount: 3,
		},
		{
			name:          "Gemini selectors",
			modelName:     "Gemini",
			expectedCount: 3,
		},
		{
			name:          "Copilot selectors",
			modelName:     "Copilot",
			expectedCount: 3,
		},
		{
			name:          "Perplexity selectors",
			modelName:     "Perplexity",
			expectedCount: 3,
		},
		{
			name:          "Qwen selectors",
			modelName:     "Qwen",
			expectedCount: 2,
		},
		{
			name:          "Llama selectors",
			modelName:     "Llama",
			expectedCount: 2,
		},
		{
			name:          "Meta selectors (alias for Llama)",
			modelName:     "Meta",
			expectedCount: 2,
		},
		{
			name:          "Grok selectors",
			modelName:     "Grok",
			expectedCount: 2,
		},
		{
			name:          "Kimi selectors",
			modelName:     "Kimi",
			expectedCount: 3,
		},
		{
			name:          "Poe selectors",
			modelName:     "Poe",
			expectedCount: 9,
		},
		{
			name:          "Unknown model",
			modelName:     "UnknownModel",
			expectedCount: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			selectors := getSelectorsForModel(tt.modelName)
			if len(selectors) != tt.expectedCount {
				t.Errorf("Expected %d selectors for %s, got %d", tt.expectedCount, tt.modelName, len(selectors))
			}
		})
	}
}

func TestGenerateSummary(t *testing.T) {
	rc := NewResponseCollector()

	// Add some test responses
	rc.AddResponse(&AIResponse{
		ModelName: "Model1",
		Status:    "success",
		Content:   "Response 1",
	})
	rc.AddResponse(&AIResponse{
		ModelName: "Model2",
		Status:    "timeout",
		Error:     "Failed to extract",
	})

	summary := rc.GenerateSummary()
	if summary == "" {
		t.Error("Expected non-empty summary")
	}
}

func TestGenerateJSON(t *testing.T) {
	rc := NewResponseCollector()
	rc.AddResponse(&AIResponse{
		ModelName: "TestModel",
		Status:    "success",
	})

	jsonData, err := rc.GenerateJSON()
	if err != nil {
		t.Errorf("Expected no error, got %v", err)
	}
	if len(jsonData) == 0 {
		t.Error("Expected non-empty JSON")
	}
}
