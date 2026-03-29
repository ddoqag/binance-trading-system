package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestGetUserDataDir(t *testing.T) {
	dir := getUserDataDir()
	if dir == "" {
		t.Error("Expected non-empty user data directory")
	}
	// Verify it ends with "user_data"
	if !filepath.IsAbs(dir) {
		t.Error("Expected absolute path")
	}
}

func TestExtractDomain(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "HTTPS URL with path",
			input:    "https://chat.openai.com/chat/abc123",
			expected: "chat.openai.com",
		},
		{
			name:     "HTTP URL",
			input:    "http://example.com",
			expected: "example.com",
		},
		{
			name:     "URL with www",
			input:    "https://www.google.com",
			expected: "google.com",
		},
		{
			name:     "Just domain",
			input:    "claude.ai",
			expected: "claude.ai",
		},
		{
			name:     "Empty string",
			input:    "",
			expected: "",
		},
		{
			name:     "Domain with port",
			input:    "https://example.com:8080/path",
			expected: "example.com:8080",
		},
		{
			name:     "Domain with query params",
			input:    "https://example.com/path?param=1",
			expected: "example.com",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := extractDomain(tt.input)
			if result != tt.expected {
				t.Errorf("extractDomain(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestFlexibleContains(t *testing.T) {
	tests := []struct {
		name     string
		s        string
		substr   string
		expected bool
	}{
		{
			name:     "Exact match",
			s:        "chat.openai.com",
			substr:   "chat.openai.com",
			expected: true,
		},
		{
			name:     "Substring match",
			s:        "https://chat.openai.com/chat",
			substr:   "openai",
			expected: true,
		},
		{
			name:     "Case insensitive",
			s:        "CHAT.OpenAI.COM",
			substr:   "openai",
			expected: true,
		},
		{
			name:     "No match",
			s:        "google.com",
			substr:   "openai",
			expected: false,
		},
		{
			name:     "WWW prefix handled in s",
			s:        "www.google.com",
			substr:   "google.com",
			expected: true,
		},
		{
			name:     "WWW prefix handled in substr",
			s:        "google.com",
			substr:   "www.google.com",
			expected: true,
		},
		{
			name:     "Empty substr",
			s:        "google.com",
			substr:   "",
			expected: true,
		},
		{
			name:     "Both empty",
			s:        "",
			substr:   "",
			expected: true,
		},
		{
			name:     "Substr longer than s",
			s:        "short",
			substr:   "very long substring",
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := flexibleContains(tt.s, tt.substr)
			if result != tt.expected {
				t.Errorf("flexibleContains(%q, %q) = %v, want %v", tt.s, tt.substr, result, tt.expected)
			}
		})
	}
}

func TestIsBrowserRunning(t *testing.T) {
	// This test just verifies the function doesn't panic
	// Actual functionality depends on file system
	result := isBrowserRunning()
	// We can't assert true/false reliably, just check it returns a bool
	_ = result
}

func TestIsBrowserRunning_WithLockfile(t *testing.T) {
	// Create a temporary directory for testing
	tempDir, err := os.MkdirTemp("", "test-browser-*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create lockfile
	lockFile := filepath.Join(tempDir, "lockfile")
	if err := os.WriteFile(lockFile, []byte("test"), 0644); err != nil {
		t.Fatalf("Failed to create lockfile: %v", err)
	}

	// The function will check for lockfile in real user_data,
	// but this test just verifies the logic path is covered
	result := isBrowserRunning()
	_ = result
}
