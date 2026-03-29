package main

import (
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/playwright-community/playwright-go"
)

// RunInspector runs the selector inspector
func RunInspector(modelNames []string) {
	models := GetModels()

	for _, model := range models {
		if len(modelNames) > 0 {
			found := false
			for _, name := range modelNames {
				if strings.EqualFold(name, model.Name) {
					found = true
					break
				}
			}
			if !found {
				continue
			}
		}

		runSingleInspection(model)
	}
}

func runSingleInspection(model AIModel) {
	fmt.Printf("\n==================================================\n")
	fmt.Printf("Inspecting: %s\n", model.Name)
	fmt.Printf("URL: %s\n", model.URL)
	fmt.Printf("==================================================\n\n")

	pw, err := playwright.Run()
	if err != nil {
		log.Fatalf("Failed to start playwright: %v", err)
	}
	defer pw.Stop()

	browser, err := pw.Chromium.Launch(playwright.BrowserTypeLaunchOptions{
		Headless: playwright.Bool(false),
		Args: []string{
			"--disable-blink-features=AutomationControlled",
			"--no-sandbox",
		},
	})
	if err != nil {
		log.Fatalf("Failed to launch browser: %v", err)
	}
	defer browser.Close()

	page, err := browser.NewPage()
	if err != nil {
		log.Fatalf("Failed to create page: %v", err)
	}

	fmt.Printf("Navigating to %s...\n", model.URL)
	if _, err := page.Goto(model.URL, playwright.PageGotoOptions{
		Timeout: playwright.Float(60000),
	}); err != nil {
		log.Fatalf("Failed to navigate: %v", err)
	}

	time.Sleep(5 * time.Second)

	fmt.Printf("\n>>> ACTION REQUIRED <<<\n")
	fmt.Printf("Please manually:\n")
	fmt.Printf("1. Type a test message (e.g., \"你好\")\n")
	fmt.Printf("2. Send the message\n")
	fmt.Printf("3. Wait for the AI to respond\n")
	fmt.Printf("\nWaiting 60 seconds...\n\n")

	time.Sleep(60 * time.Second)

	fmt.Printf("Analyzing page structure...\n\n")
	fmt.Printf("========== DOM ANALYSIS FOR %s ==========\n\n", model.Name)

	// Simple analysis using JavaScript
	script := `
		const results = [];
		const commonSelectors = [
			'[class*="message"]',
			'[class*="chat"]',
			'[class*="response"]',
			'[class*="assistant"]',
			'[class*="ai"]',
			'[class*="bot"]',
			'[role="article"]'
		];

		commonSelectors.forEach(sel => {
			try {
				const els = document.querySelectorAll(sel);
				if (els.length > 0) {
					results.push({
						selector: sel,
						count: els.length,
						sample: els[els.length - 1].tagName + ' | ' +
						        els[els.length - 1].className.substring(0, 50)
					});
				}
			} catch(e) {}
		});

		return JSON.stringify(results, null, 2);
	`

	result, err := page.Evaluate(script)
	if err != nil {
		fmt.Printf("Error running analysis: %v\n", err)
	} else {
		fmt.Printf("Matching elements found:\n%s\n\n", result)
	}

	fmt.Printf("========== END OF ANALYSIS ==========\n")
	fmt.Printf("\nPlease manually inspect the page to find the exact class names.\n")
	fmt.Printf("Look for the element containing the AI's response text.\n\n")
}
