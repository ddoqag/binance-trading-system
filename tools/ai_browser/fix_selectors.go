package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strings"
	"time"
)

// ModelSelectorFix contains the correct selectors for each model
type ModelSelectorFix struct {
	Name            string
	URL             string
	InputSelector   string // Where to type the question
	ResponseSelectors []string // Where to find the AI response
	WaitTime        time.Duration // How long to wait for response
	Notes           string
}

// GetFixedSelectors returns the corrected selectors for all models
func GetFixedSelectors() []ModelSelectorFix {
	return []ModelSelectorFix{
		{
			Name:          "ChatGPT",
			URL:           "https://chat.openai.com",
			InputSelector: "#prompt-textarea",
			ResponseSelectors: []string{
				"[data-testid='conversation-turn-2']",
				"main .group:not(:has(textarea)) .prose",
				"[data-message-author-role='assistant'] .prose",
			},
			WaitTime: 60 * time.Second,
			Notes:      "Turn 2 is the first assistant response",
		},
		{
			Name:          "Gemini",
			URL:           "https://gemini.google.com",
			InputSelector: "textarea[placeholder][aria-label]",
			ResponseSelectors: []string{
				"[data-testid='content-container']",
				"model-response .response-content",
				".conversation-container .response-container:last-child",
				"[data-testid*='response']",
			},
			WaitTime: 60 * time.Second,
			Notes:      "Need to avoid sidebar elements",
		},
		{
			Name:          "Copilot",
			URL:           "https://copilot.microsoft.com",
			InputSelector: "#userInput",
			ResponseSelectors: []string{
				"[class*='ac-textBlock']",
				".cib-serp-main .cib-chat-turn:last-child",
				"[class*='chat-turn']:last-child [class*='text-block']",
			},
			WaitTime: 60 * time.Second,
			Notes:      "Working well with current selectors",
		},
		{
			Name:          "Doubao",
			URL:           "https://www.doubao.com",
			InputSelector: "textarea[placeholder*='输入']",
			ResponseSelectors: []string{
				"[class*='assistant'] [class*='message-content']",
				"[class*='chat-message']:last-child [class*='content']",
				".message-list .assistant-message:last-child",
				"[data-testid*='assistant-message']",
			},
			WaitTime: 90 * time.Second,
			Notes:      "Chinese model, may have different class names",
		},
		{
			Name:          "Yuanbao",
			URL:           "https://yuanbao.tencent.com",
			InputSelector: "[contenteditable='true'][placeholder]",
			ResponseSelectors: []string{
				"[class*='bot-message'] [class*='content']",
				"[class*='chat-item']:last-child [class*='reply']",
				".chat-history .assistant:last-child",
				"[data-testid*='bot']",
			},
			WaitTime: 90 * time.Second,
			Notes:      "Tencent model, may use different terminology (bot vs assistant)",
		},
		{
			Name:          "Antafu",
			URL:           "https://chat.antafu.com",
			InputSelector: "textarea[placeholder]",
			ResponseSelectors: []string{
				"[class*='ai-response']",
				"[class*='message']:last-child [class*='text']",
				".conversation .ai:last-child",
				"[data-testid*='ai-message']",
			},
			WaitTime: 90 * time.Second,
			Notes:      "Smaller provider, DOM structure may be simpler",
		},
		{
			Name:          "Llama",
			URL:           "https://www.meta.ai",
			InputSelector: "[contenteditable='true']",
			ResponseSelectors: []string{
				"[role='article']",
				"[class*='response-card']",
				"[data-testid*='response']",
			},
			WaitTime: 60 * time.Second,
			Notes:      "Meta's Llama, may have unique structure",
		},
		{
			Name:          "Grok",
			URL:           "https://grok.x.ai",
			InputSelector: "textarea",
			ResponseSelectors: []string{
				"[class*='message-content']",
				"[class*='response-text']",
			},
			WaitTime: 60 * time.Second,
			Notes:      "X's Grok, may have simple structure",
		},
		{
			Name:          "Poe",
			URL:           "https://poe.com",
			InputSelector: "textarea",
			ResponseSelectors: []string{
				"[class*='ChatMessage']",
				"[class*='Message']",
				"[class*='bot-message']",
			},
			WaitTime: 60 * time.Second,
			Notes:      "Poe has multiple bots, structure may vary",
		},
	}
}

// RunSelectorFix applies the fixed selectors to a test
func RunSelectorFix() {
	fixes := GetFixedSelectors()

	fmt.Println("=============================================")
	fmt.Println("     SELECTOR FIX RECOMMENDATIONS")
	fmt.Println("=============================================")
	fmt.Println()

	for _, fix := range fixes {
		fmt.Printf("MODEL: %s\n", fix.Name)
		fmt.Printf("URL: %s\n", fix.URL)
		fmt.Printf("Input Selector: %s\n", fix.InputSelector)
		fmt.Printf("Response Selectors:\n")
		for _, sel := range fix.ResponseSelectors {
			fmt.Printf("  - %s\n", sel)
		}
		fmt.Printf("Wait Time: %v\n", fix.WaitTime)
		fmt.Printf("Notes: %s\n", fix.Notes)
		fmt.Println("---------------------------------------------")
		fmt.Println()
	}

	// Save to file
	SaveSelectorFixes(fixes)
}

// SaveSelectorFixes saves the fixes to a file
func SaveSelectorFixes(fixes []ModelSelectorFix) {
	filename := "selector_fixes.json"

	data := make(map[string]interface{})
	for _, fix := range fixes {
		data[fix.Name] = map[string]interface{}{
			"url":               fix.URL,
			"input_selector":    fix.InputSelector,
			"response_selectors": fix.ResponseSelectors,
			"wait_time":         fix.WaitTime.String(),
			"notes":             fix.Notes,
		}
	}

	jsonData, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		log.Printf("Failed to marshal JSON: %v", err)
		return
	}

	if err := os.WriteFile(filename, jsonData, 0644); err != nil {
		log.Printf("Failed to write file: %v", err)
		return
	}

	fmt.Printf("Selector fixes saved to: %s\n", filename)
}

// ValidateSelectors tests the selectors for a specific model
func ValidateSelectors(modelName string) {
	fixes := GetFixedSelectors()

	var target *ModelSelectorFix
	for i := range fixes {
		if strings.EqualFold(fixes[i].Name, modelName) {
			target = &fixes[i]
			break
		}
	}

	if target == nil {
		fmt.Printf("Model %s not found\n", modelName)
		return
	}

	fmt.Printf("Validating selectors for %s...\n", target.Name)
	fmt.Printf("URL: %s\n", target.URL)
	fmt.Printf("\nRecommended Input Selector:\n  %s\n", target.InputSelector)
	fmt.Printf("\nRecommended Response Selectors:\n")
	for _, sel := range target.ResponseSelectors {
		fmt.Printf("  - %s\n", sel)
	}

	fmt.Printf("\nTo verify these selectors:\n")
	fmt.Printf("1. Open the browser and navigate to: %s\n", target.URL)
	fmt.Printf("2. Open DevTools (F12)\n")
	fmt.Printf("3. Use the element picker to inspect the input box and AI response\n")
	fmt.Printf("4. Compare with the recommended selectors above\n")
}
