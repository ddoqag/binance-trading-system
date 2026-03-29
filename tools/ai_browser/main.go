package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/playwright-community/playwright-go"
)

const (
	chromePath  = "C:/Program Files/Google/Chrome/Application/chrome.exe"
	cdpEndpoint = "http://localhost:9222"
	debugPort   = "9222"
	configFile  = "conversation.json"
)

// userDataDir can be overridden via -user-data flag before browser launch.
var userDataDir string

func getUserDataDir() string {
	if userDataDir != "" {
		return userDataDir
	}
	cwd, err := os.Getwd()
	if err != nil {
		log.Fatalf("Failed to get working dir: %v", err)
	}
	return filepath.Join(cwd, "user_data")
}

func isBrowserRunning() bool {
	lockFile := filepath.Join(getUserDataDir(), "lockfile")
	if _, err := os.Stat(lockFile); err == nil {
		return true
	}
	return false
}

// tryConnectCDP attempts to connect to an existing browser via CDP
func tryConnectCDP() (playwright.BrowserContext, *playwright.Playwright, bool) {
	pw, err := playwright.Run()
	if err != nil {
		return nil, nil, false
	}

	browser, err := pw.Chromium.ConnectOverCDP(cdpEndpoint)
	if err != nil {
		pw.Stop()
		return nil, nil, false
	}

	// Get browser context
	contexts := browser.Contexts()
	if len(contexts) > 0 {
		return contexts[0], pw, true
	}

	// Create new context if none exists
	ctx, err := browser.NewContext()
	if err != nil {
		browser.Close()
		pw.Stop()
		return nil, nil, false
	}

	return ctx, pw, true
}

// launchNewBrowser starts a new browser with CDP enabled
func launchNewBrowser() (playwright.BrowserContext, *playwright.Playwright, error) {
	userDataDir := getUserDataDir()

	if err := os.MkdirAll(userDataDir, 0755); err != nil {
		return nil, nil, fmt.Errorf("failed to create user_data dir: %w", err)
	}

	pw, err := playwright.Run()
	if err != nil {
		return nil, nil, fmt.Errorf("failed to start playwright: %w", err)
	}

	// Launch with CDP enabled for future connections
	browserContext, err := pw.Chromium.LaunchPersistentContext(userDataDir, playwright.BrowserTypeLaunchPersistentContextOptions{
		Headless: playwright.Bool(false),
		Args: []string{
			"--disable-blink-features=AutomationControlled",
			"--no-sandbox",
			fmt.Sprintf("--remote-debugging-port=%s", debugPort),
		},
		ExecutablePath: playwright.String(chromePath),
		Viewport: &playwright.Size{
			Width:  1280,
			Height: 720,
		},
	})
	if err != nil {
		pw.Stop()
		return nil, nil, fmt.Errorf("failed to launch browser: %w", err)
	}

	return browserContext, pw, nil
}

// checkExistingPage checks if a page with the given URL pattern already exists
func checkExistingPage(browserContext playwright.BrowserContext, urlPattern string) playwright.Page {
	pages := browserContext.Pages()
	for _, page := range pages {
		url := page.URL()
		log.Printf("[DEBUG] Checking page: %s against pattern: %s", url, urlPattern)
		// Check if URL contains the domain - use flexible string matching
		if flexibleContains(url, urlPattern) {
			log.Printf("[DEBUG] Found existing page for %s: %s", urlPattern, url)
			return page
		}
	}
	log.Printf("[DEBUG] No existing page found for %s", urlPattern)
	return nil
}

// flexibleContains checks if string contains substring (flexible matching)
func flexibleContains(s, substr string) bool {
	s = strings.ToLower(s)
	substr = strings.ToLower(substr)

	// Remove www. prefix for matching
	s = strings.TrimPrefix(s, "www.")
	substr = strings.TrimPrefix(substr, "www.")

	// Extract just the domain part for more precise matching
	// Remove protocol
	s = strings.TrimPrefix(s, "https://")
	s = strings.TrimPrefix(s, "http://")
	substr = strings.TrimPrefix(substr, "https://")
	substr = strings.TrimPrefix(substr, "http://")

	// Get domain part before first slash
	if idx := strings.Index(s, "/"); idx != -1 {
		s = s[0:idx]
	}
	if idx := strings.Index(substr, "/"); idx != -1 {
		substr = substr[0:idx]
	}

	// Use standard strings.Contains for simplicity and reliability
	return strings.Contains(s, substr)
}

// extractDomain extracts domain from URL for matching
func extractDomain(url string) string {
	// Remove protocol
	url = strings.TrimPrefix(url, "https://")
	url = strings.TrimPrefix(url, "http://")
	url = strings.TrimPrefix(url, "www.")

	// Remove path
	if idx := strings.Index(url, "/"); idx != -1 {
		url = url[0:idx]
	}
	return url
}

// openModelPage opens a single AI model page (or activates existing)
func openModelPage(browserContext playwright.BrowserContext, model AIModel, config *ConversationConfig, outputDir string) {
	domain := extractDomain(model.URL)

	// Check if page already exists
	if existingPage := checkExistingPage(browserContext, domain); existingPage != nil {
		log.Printf("[%s] Page already open, reusing (login preserved)", model.Name)
		// Note: We don't reload to preserve login state and any ongoing conversations
		// Just bring to front and send message
		if err := existingPage.BringToFront(); err != nil {
			log.Printf("[%s] Failed to bring to front: %v", model.Name, err)
		}
		// Send message on existing page
		sendMessageToPage(existingPage, model, config, outputDir)
		return
	}

	// Create new page
	page, err := browserContext.NewPage()
	if err != nil {
		log.Printf("[%s] Failed to create page: %v", model.Name, err)
		return
	}

	// Navigate to AI model
	log.Printf("[%s] Opening %s...", model.Name, model.URL)
	if _, err := page.Goto(model.URL, playwright.PageGotoOptions{
		Timeout: playwright.Float(90000),
	}); err != nil {
		log.Printf("[%s] Failed to navigate: %v", model.Name, err)
		return
	}

	// Wait for page to load - longer wait for complex apps
	loadTime := 3 * time.Second
	if model.Name == "Claude" || model.Name == "ChatGPT" || model.Name == "Poe" {
		loadTime = 5 * time.Second
	}
	if model.Name == "Doubao" || model.Name == "Yuanbao" {
		loadTime = 6 * time.Second
	}
	time.Sleep(loadTime)

	// Send message
	sendMessageToPage(page, model, config, outputDir)
}

// sendMessageToPage sends message to an existing page
func sendMessageToPage(page playwright.Page, model AIModel, config *ConversationConfig, outputDir string) {
	// Wait for page to be ready - longer wait for complex apps
	waitTime := 3 * time.Second
	if model.Name == "Claude" || model.Name == "ChatGPT" || model.Name == "Poe" {
		waitTime = 6 * time.Second
	}
	if model.Name == "Doubao" || model.Name == "Yuanbao" {
		waitTime = 7 * time.Second
	}
	time.Sleep(waitTime)

	// Get the prompt for this model
	prompt := config.GetPromptForModel(model)

	// Build selectors: first use model-specific, then fall back to generic
	var inputSelectors []string
	if model.InputSelector != "" {
		// Split comma-separated selectors
		for _, s := range strings.Split(model.InputSelector, ",") {
			inputSelectors = append(inputSelectors, strings.TrimSpace(s))
		}
	}
	// Add generic fallbacks
	inputSelectors = append(inputSelectors,
		"textarea[placeholder]",
		"textarea",
		"[contenteditable='true']",
		"input[type='text']",
		"div[role='textbox']",
		"[contenteditable]",
	)

	for _, selector := range inputSelectors {
		locator := page.Locator(selector).First()
		count, _ := locator.Count()
		if count == 0 {
			continue
		}

		visible, _ := locator.IsVisible()
		if !visible {
			continue
		}

		log.Printf("[%s] Found input with selector: %s", model.Name, selector)

		// Click to focus
		if err := locator.Click(); err != nil {
			continue
		}

		// Small wait after click
		time.Sleep(800 * time.Millisecond)

		// Clear existing content first (Ctrl+A then Delete)
		_ = locator.Press("Control+a")
		time.Sleep(200 * time.Millisecond)
		_ = locator.Press("Delete")
		time.Sleep(300 * time.Millisecond)

		// Type the prompt
		if err := locator.Fill(prompt); err != nil {
			log.Printf("[%s] Failed to fill: %v", model.Name, err)
			continue
		}

		// Wait a bit for input to settle
		time.Sleep(500 * time.Millisecond)

		// Try submit: for some models, prefer Enter key over button click
		submitted := false

		// For Yuanbao and Antafu, use Enter directly (they have tricky button selectors
		preferEnter := model.Name == "Yuanbao" || model.Name == "Antafu" || model.Name == "Copilot"

		if !preferEnter && model.SubmitSelector != "" {
			// Try model-specific submit selector first (for other models)
			for _, sel := range strings.Split(model.SubmitSelector, ",") {
				sel = strings.TrimSpace(sel)
				submitBtn := page.Locator(sel).First()
				if cnt, _ := submitBtn.Count(); cnt > 0 {
					if vis, _ := submitBtn.IsVisible(); vis {
						log.Printf("[%s] Clicking submit button with selector: %s", model.Name, sel)
						if err := submitBtn.Click(); err == nil {
							submitted = true
							break
						}
					}
				}
			}
		}

		// If no button click worked, or we prefer Enter, try pressing Enter
		if !submitted || preferEnter {
			log.Printf("[%s] Pressing Enter to submit", model.Name)
			_ = locator.Press("Enter")
			time.Sleep(200 * time.Millisecond)
			// Try Shift+Enter for multi-line
			_ = locator.Press("Shift+Enter")
		}

		log.Printf("[%s] Message sent!", model.Name)

		// Take screenshot after sending for debugging
		screenshotPath := fmt.Sprintf("%s/screenshot_%s_%d.png", outputDir, model.Name, time.Now().Unix())
		if _, err := page.Screenshot(playwright.PageScreenshotOptions{
			Path: playwright.String(screenshotPath),
		}); err != nil {
			log.Printf("[%s] Failed to take screenshot: %v", model.Name, err)
		} else {
			log.Printf("[%s] Screenshot saved: %s", model.Name, screenshotPath)
		}

		return
	}

	log.Printf("[%s] Could not find input field (may need manual input)", model.Name)
}

func main() {
	// Parse flags
	var (
		initConfig   = flag.Bool("init", false, "Create default config file")
		question     = flag.String("q", "", "Question to ask (overrides config)")
		listModels   = flag.Bool("list", false, "List available AI models")
		waitResponse = flag.Bool("wait", false, "Wait for responses and generate summary")
		outputDir    = flag.String("output", "./output", "Output directory for summaries")
		inspect      = flag.String("inspect", "", "Inspect model selectors (e.g., 'all' or 'Doubao,ChatGPT')")
		domesticOnly = flag.Bool("in", false, "Only use Chinese domestic AI models (国内)")
		overseasOnly = flag.Bool("out", false, "Only use overseas AI models (国外)")
		// trading mode: reads market_query.json, uses domestic models, auto-exits after saving
		tradingMode = flag.Bool("trading", false, "Trading mode: read market_query.json, collect and exit (no Ctrl+C needed)")
		// override user_data dir (e.g. reuse login sessions from another instance)
		userDataOverride = flag.String("user-data", "", "Override user_data directory path")
	)
	flag.Parse()

	// apply user_data override before any browser operations
	if *userDataOverride != "" {
		userDataDir = *userDataOverride
	}

	// -trading implies -wait and uses market_query.json as config.
	// All models are used by default; add -in or -out to filter by region.
	if *tradingMode {
		*waitResponse = true
	}

	// Inspector mode
	if *inspect != "" {
		var modelsToInspect []string
		if *inspect == "all" {
			filtered := GetFilteredModels(*domesticOnly, *overseasOnly)
			for _, m := range filtered {
				modelsToInspect = append(modelsToInspect, m.Name)
			}
		} else {
			modelsToInspect = strings.Split(*inspect, ",")
			for i := range modelsToInspect {
				modelsToInspect[i] = strings.TrimSpace(modelsToInspect[i])
			}
		}
		RunInspector(modelsToInspect)
		return
	}

	// List models mode
	if *listModels {
		models := GetFilteredModels(*domesticOnly, *overseasOnly)
		fmt.Println("Available AI Models:")
		for i, model := range models {
			regionLabel := "[国内]"
			if model.Region == RegionOverseas {
				regionLabel = "[国外]"
			}
			fmt.Printf("%2d. %-12s %s - %s\n", i+1, model.Name, regionLabel, model.URL)
			fmt.Printf("    Role: %s\n", model.RolePrompt)
			fmt.Println()
		}
		return
	}

	// Init config mode
	if *initConfig {
		config := DefaultConfig()
		if err := config.SaveConfig(configFile); err != nil {
			log.Fatalf("Failed to save config: %v", err)
		}
		log.Printf("Created default config: %s", configFile)
		log.Println("Edit this file to customize your questions and prompts.")
		return
	}

	// Load configuration: trading mode reads market_query.json, else conversation.json
	cfgFile := configFile
	if *tradingMode {
		cfgFile = "market_query.json"
	}
	config, err := LoadConfig(cfgFile)
	if err != nil {
		log.Printf("Warning: Could not load config %s: %v, using defaults", cfgFile, err)
		config = DefaultConfig()
	}

	// Override question if provided via flag
	if *question != "" {
		config.Question = *question
	}

	log.Println("==================================================")
	log.Println("AI Model Comparison Tool")
	log.Println("==================================================")
	log.Printf("Question: %s", config.Question)
	models := GetFilteredModels(*domesticOnly, *overseasOnly)
	var modeLabel string
	switch {
	case *domesticOnly:
		modeLabel = " (国内模型 only)"
	case *overseasOnly:
		modeLabel = " (国外模型 only)"
	default:
		modeLabel = " (全部模型)"
	}
	log.Printf("Models: %d%s", len(models), modeLabel)
	log.Println()

	var browserContext playwright.BrowserContext
	var pw *playwright.Playwright
	var isExistingBrowser bool

	// Strategy: First try to connect via CDP, then check lockfile
	log.Println("Checking for existing browser via CDP...")
	ctx, p, connected := tryConnectCDP()
	if connected {
		browserContext = ctx
		pw = p
		isExistingBrowser = true
		log.Println("Connected to existing browser via CDP!")
		log.Println("  Note: Your login sessions are preserved in user_data/ directory!")
	} else if isBrowserRunning() {
		// Browser is running but CDP not available
		log.Println("WARNING: Browser is running but CDP port not available")
		log.Printf("Please restart Chrome with: --remote-debugging-port=%s", debugPort)
		log.Println("Or close the browser and let this tool launch it")
		os.Exit(1)
	} else {
		// No browser running, launch new one
		log.Println("No existing browser found, launching new...")
		ctx, p, err := launchNewBrowser()
		if err != nil {
			log.Fatalf("Failed to launch browser: %v", err)
		}
		browserContext = ctx
		pw = p
		isExistingBrowser = false
		log.Println("New browser launched with CDP enabled on port", debugPort)
		log.Println("  Login sessions will be preserved for future runs!")
		// Wait for browser to fully initialize
		time.Sleep(2 * time.Second)
	}

	// Open all AI model pages
	for i, model := range models {
		go openModelPage(browserContext, model, config, *outputDir)
		time.Sleep(800 * time.Millisecond)

		// Log progress every 3 models
		if (i+1)%3 == 0 || i == len(models)-1 {
			log.Printf("Progress: %d/%d models opened...", i+1, len(models))
		}
	}

	log.Println()
	log.Println("All model pages launched!")
	if isExistingBrowser {
		log.Println("Using your existing logged-in browser session.")
	}

	// If wait flag is set, collect responses and generate summary
	if *waitResponse {
		log.Println()
		log.Println("Waiting for responses (this may take 1-3 minutes)...")
		log.Println()

		collector := NewResponseCollector()

		// Give AI models time to generate responses
		waitTime := time.Duration(config.ResponseWaitTime) * time.Second
		if waitTime < 60*time.Second {
			waitTime = 90 * time.Second
		}

		log.Printf("Waiting %v for responses...", waitTime)
		time.Sleep(waitTime)

		// Collect responses from all pages
		pages := browserContext.Pages()
		for _, page := range pages {
			url := page.URL()
			// Find which model this page belongs to
			for _, model := range models {
				if flexibleContains(url, extractDomain(model.URL)) {
					log.Printf("[%s] Collecting response...", model.Name)
					// Longer timeout for Chinese models that might need more time
					collectTimeout := 45 * time.Second
					if model.Name == "Doubao" || model.Name == "Yuanbao" || model.Name == "Antafu" || model.Name == "Copilot" {
						collectTimeout = 90 * time.Second
					}
					resp := CollectFromPage(page, model, config.Question, collectTimeout)
					collector.AddResponse(resp)
					break
				}
			}
		}

		// Generate and save summary
		log.Println()
		log.Println("Generating summary...")
		summary := collector.GenerateSummary()

		// Always print summary to console first
		fmt.Println()
		fmt.Println("=")
		fmt.Println("AI MODEL COMPARISON SUMMARY")
		fmt.Println("=")
		fmt.Println(summary)
		fmt.Println("=")

		// Then save to file
		if err := collector.SaveToFile(*outputDir); err != nil {
			log.Printf("Failed to save summary: %v", err)
		} else {
			log.Println("Summary printed to console and saved to file!")
		}

		// trading mode: auto-exit after saving, no Ctrl+C needed
		if *tradingMode {
			log.Println("Trading mode: collection complete, exiting.")
			if !isExistingBrowser {
				if browserContext != nil {
					browserContext.Close()
				}
				if pw != nil {
					pw.Stop()
				}
			}
			return
		}
	}

	log.Println()
	log.Println("Press Ctrl+C to exit (browser will remain open if it was already running).")
	log.Println()

	// Wait for interrupt
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	<-sigChan

	log.Println("\nShutting down...")

	// Only close browser if we launched it
	if !isExistingBrowser {
		if browserContext != nil {
			browserContext.Close()
		}
		if pw != nil {
			pw.Stop()
		}
	}
}

// GetFilteredModels returns models based on the -in and -out flags
func GetFilteredModels(domesticOnly, overseasOnly bool) []AIModel {
	switch {
	case domesticOnly && overseasOnly:
		log.Println("Warning: Both -in and -out flags specified, using all models")
		return GetModels()
	case domesticOnly:
		return GetDomesticModels()
	case overseasOnly:
		return GetOverseasModels()
	default:
		return GetModels()
	}
}
