package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/playwright-community/playwright-go"
)

// ResponseCollector collects AI responses
type ResponseCollector struct {
	Responses map[string]*AIResponse
	mu        chan struct{}
}

// AIResponse represents a single AI's response
type AIResponse struct {
	ModelName string    `json:"model_name"`
	URL       string    `json:"url"`
	Question  string    `json:"question"`
	Content   string    `json:"content"`
	Status    string    `json:"status"` // pending, success, error
	Error     string    `json:"error,omitempty"`
	Timestamp time.Time `json:"timestamp"`
}

// NewResponseCollector creates a new collector
func NewResponseCollector() *ResponseCollector {
	return &ResponseCollector{
		Responses: make(map[string]*AIResponse),
		mu:        make(chan struct{}, 1),
	}
}

// AddResponse adds a response to the collector
func (rc *ResponseCollector) AddResponse(resp *AIResponse) {
	rc.mu <- struct{}{}
	defer func() { <-rc.mu }()
	rc.Responses[resp.ModelName] = resp
}

// GetResponse gets a response by model name
func (rc *ResponseCollector) GetResponse(modelName string) *AIResponse {
	rc.mu <- struct{}{}
	defer func() { <-rc.mu }()
	return rc.Responses[modelName]
}

// getSelectorsForModel returns model-specific selectors
func getSelectorsForModel(modelName string) []string {
	switch modelName {
	case "ChatGPT":
		return []string{
			"[data-testid*='conversation-turn']:last-child",
			".markdown.prose",
			"[data-message-author-role='assistant']",
		}
	case "Claude":
		return []string{
			"[data-testid*='message-assistant']",
			".font-claude-message",
			"prose",
		}
	case "Gemini":
		return []string{
			"[data-testid*='response']",
			"[class*='response'] [class*='content']",
			"[class*='message-content']:last-child",
			"main [class*='content']:last-child",
			"article:last-child",
		}
	case "Copilot":
		return []string{
			// Microsoft Copilot specific selectors
			"[class*='chat'] [class*='content']",
			"[class*='message'] [class*='text']",
			"[class*='response'] [class*='content']",
			"[class*='bot'] [class*='message']",
			"[class*='assistant'] [class*='text']",
			"[role='main'] [class*='content']",
			"main [class*='chat']",
			"[data-testid*='message']",
			"[data-testid*='response']",
			"[data-testid*='chat']",
			// More generic selectors for modern Copilot UI
			"article[class*='message']",
			"div[class*='message']:not([class*='user'])",
			"div[class*='bubble']:not([class*='user'])",
			"[class*='text-block']",
			"[class*='text-content']",
			"[class*='markdown']",
			".prose",
			"article:last-child",
			"main div:last-child",
			"[role='article']:last-child",
		}
	case "Perplexity":
		return []string{
			"[class*='answer']",
			"[class*='response']",
			"[data-testid*='answer']",
		}
	case "Qwen":
		return []string{
			"[class*='message-assistant']",
			"[class*='response']",
		}
	case "Doubao":
		return []string{
			// 基于截图的豆包选择器 - 对话气泡
			"[class*='message']:not([class*='user']):last-child",
			"[class*='bubble']:not([class*='user']):last-child",
			"[class*='chat'] [class*='message']:last-child",
			// 排除侧边栏的选择器
			":not([class*='sidebar']) [class*='message']:last-child",
			":not([class*='menu']) [class*='content']:last-child",
			// 更广泛的选择器
			"main [class*='message']:last-child",
			"[class*='assistant']:last-child",
			"[class*='message-content']:last-child",
		}
	case "Yuanbao":
		return []string{
			// 元宝更广泛的选择器
			"[class*='message-content']:last-child",
			"[class*='response']:last-child",
			"[class*='answer']:last-child",
			"main [class*='content']:last-child",
			"article:last-child",
			"[role='article']:last-child",
			// 排除用户消息的选择器
			"[class*='message']:not([class*='user']):last-child",
			"[class*='bubble']:not([class*='user']):last-child",
			"[class*='bot']:last-child",
			"[class*='assistant']:last-child",
		}
	case "Antafu":
		return []string{
			// 阿福更广泛的选择器
			"[class*='message-content']:last-child",
			"[class*='response']:last-child",
			"[class*='answer']:last-child",
			"main [class*='content']:last-child",
			"article:last-child",
			"[role='article']:last-child",
			// 排除用户消息的选择器
			"[class*='message']:not([class*='user']):last-child",
			"[class*='bubble']:not([class*='user']):last-child",
			"[class*='ai']:last-child",
			"[class*='assistant']:last-child",
		}
	case "Grok":
		return []string{
			"[class*='message-assistant']",
			"[class*='response']",
		}
	case "Kimi":
		return []string{
			"[class*='message']",
			"[class*='response']",
			"[contenteditable='false']",
		}
	case "Poe":
		return []string{
			"[class*='ChatMessage']:last-child [class*='Message']",  // 最后一条聊天消息
			"[class*='ChatMessage']:last-child .prose",             // 最后一条消息的Markdown
			"[class*='ChatMessage']:last-child .markdown-body",     // 最后一条消息的内容
			"[class*='message']:not([class*='user']):last-child",    // 非用户消息的最后一条
		}
	default:
		return []string{}
	}
}

// CollectFromPage extracts response from a page
func CollectFromPage(page playwright.Page, model AIModel, question string, timeout time.Duration) *AIResponse {
	resp := &AIResponse{
		ModelName: model.Name,
		URL:       page.URL(),
		Question:  question,
		Status:    "pending",
		Timestamp: time.Now(),
	}

	// Get model-specific selectors first
	modelSelectors := getSelectorsForModel(model.Name)

	// Combine with generic selectors
	allSelectors := append(modelSelectors, []string{
		"[data-testid='conversation-turn-2']",
		"[data-testid*='turn']",
		".message-content",
		".response-content",
		"[class*='response']",
		"[class*='message']",
		"article",
		".markdown-body",
		"[role='article']",
		"main div:last-child",
		"body div:last-child",
	}...)

	// Use lower threshold for Chinese models and Copilot
	minLength := 50
	if model.Name == "Doubao" || model.Name == "Yuanbao" || model.Name == "Antafu" || model.Name == "Copilot" {
		minLength = 20
	}

	log.Printf("[%s] Starting response collection (min length: %d)...", model.Name, minLength)

	// Debug: For Copilot, print page structure on first check
	if model.Name == "Copilot" {
		debugPageContent(page)
	}

	// Wait for response to appear
	deadline := time.Now().Add(timeout)
	checkCount := 0
	for time.Now().Before(deadline) {
		checkCount++

		// Debug: For Copilot, print some content every 10 checks
		if model.Name == "Copilot" && checkCount%10 == 0 {
			debugPageContent(page)
		}

		for _, selector := range allSelectors {
			content, err := extractContent(page, selector)
			if err == nil && len(content) > minLength {
				// Skip if content looks like the question itself
				if strings.TrimSpace(content) == strings.TrimSpace(question) {
					continue
				}
				// Clean up the content - remove the question if it appears at the beginning
				cleanContent := cleanResponse(content, question)
				if len(cleanContent) > minLength {
					log.Printf("[%s] Found content with selector: %s (length: %d)", model.Name, selector, len(cleanContent))
					resp.Content = cleanContent
					resp.Status = "success"
					return resp
				}
			}
		}

		// Log progress every 5 checks
		if checkCount%5 == 0 {
			log.Printf("[%s] Still waiting for response... (check %d)", model.Name, checkCount)
		}

		time.Sleep(2 * time.Second)
	}

	log.Printf("[%s] Timed out after %v", model.Name, timeout)
	resp.Status = "timeout"
	resp.Error = "Failed to extract response within timeout"
	return resp
}

// cleanResponse removes the question from the beginning of the response if present
func cleanResponse(content, question string) string {
	content = strings.TrimSpace(content)
	question = strings.TrimSpace(question)

	// Reject welcome messages and onboarding content
	lowerContent := strings.ToLower(content)
	welcomePatterns := []string{
		"你好", "hello", "hi", "很高兴", "welcome",
		"我是", "i'm", "i am", "my name is",
		"我能为你做什么", "what can i do", "how can i help",
		"创意伙伴", "creative partner", "百科全书",
		"文件拖动", "上传文件", "支持文件格式",
		"先从哪个话题", "哪个话题开始",
	}
	for _, pattern := range welcomePatterns {
		if strings.Contains(lowerContent, pattern) && len(content) < 500 {
			// If it's a short welcome-like message, reject
			return ""
		}
	}

	// Reject if content looks like a menu/sidebar (short lines, no real content)
	lines := strings.Split(content, "\n")
	shortLineCount := 0
	for _, line := range lines {
		if len(strings.TrimSpace(line)) < 15 {
			shortLineCount++
		}
	}
	// If most lines are short, likely a menu/sidebar
	if len(lines) > 2 && shortLineCount >= len(lines)*2/3 {
		return ""
	}

	// Reject if content is exactly the question
	if content == question {
		return ""
	}

	// Reject if content contains the question and not much else
	if strings.Contains(content, question) && len(content) < len(question)*2 {
		return ""
	}

	// Try to remove the question from the beginning if it's there
	if len(content) > len(question) && strings.HasPrefix(content, question) {
		content = strings.TrimSpace(content[len(question):])
		if content == "" {
			return ""
		}
	}

	// Also try to remove just the first line if it looks like the question
	if len(lines) > 1 {
		firstLine := strings.TrimSpace(lines[0])
		if strings.Contains(firstLine, "请评价") || strings.Contains(firstLine, "评价以下") {
			content = strings.TrimSpace(strings.Join(lines[1:], "\n"))
		}
		// Also remove role prompts that may appear at the beginning
		firstLineLower := strings.ToLower(firstLine)
		if strings.Contains(firstLineLower, "you are a") || strings.Contains(firstLineLower, "provide comprehensive") {
			for i, line := range lines {
				line = strings.TrimSpace(line)
				if line != "" && !strings.Contains(strings.ToLower(line), "you are a") && !strings.Contains(strings.ToLower(line), "provide comprehensive") {
					content = strings.TrimSpace(strings.Join(lines[i:], "\n"))
					break
				}
			}
		}
	}

	// Additional cleanup: remove any system prompts at the beginning
	contentLines := strings.Split(content, "\n")
	var cleanedLines []string
	skipped := 0
	for _, line := range contentLines {
		lineTrimmed := strings.TrimSpace(line)
		if lineTrimmed == "" {
			cleanedLines = append(cleanedLines, line)
			continue
		}
		lowerLine := strings.ToLower(lineTrimmed)
		if skipped < 3 && (strings.Contains(lowerLine, "you are") ||
			strings.Contains(lowerLine, "general knowledge") ||
			strings.Contains(lowerLine, "expert") ||
			strings.Contains(lowerLine, "well-structured")) {
			skipped++
			continue
		}
		cleanedLines = append(cleanedLines, line)
	}
	content = strings.TrimSpace(strings.Join(cleanedLines, "\n"))

	if strings.TrimSpace(content) == strings.TrimSpace(question) {
		return ""
	}

	return content
}

// extractContent tries to extract text content from a selector
func extractContent(page playwright.Page, selector string) (string, error) {
	locator := page.Locator(selector).Last()
	count, err := locator.Count()
	if err != nil || count == 0 {
		return "", fmt.Errorf("not found")
	}

	// Try to get inner text
	text, err := locator.InnerText()
	if err != nil || len(strings.TrimSpace(text)) == 0 {
		// Fall back to text content
		text, err = locator.TextContent()
		if err != nil {
			return "", err
		}
	}

	return strings.TrimSpace(text), nil
}

// GenerateSummary creates a summary of all responses
func (rc *ResponseCollector) GenerateSummary() string {
	rc.mu <- struct{}{}
	defer func() { <-rc.mu }()

	var sb strings.Builder
	sb.WriteString("# AI Model Comparison Summary\n\n")
	sb.WriteString(fmt.Sprintf("Generated: %s\n\n", time.Now().Format("2006-01-02 15:04:05")))

	// Count statistics
	successCount := 0
	errorCount := 0
	for _, resp := range rc.Responses {
		if resp.Status == "success" {
			successCount++
		} else {
			errorCount++
		}
	}

	sb.WriteString(fmt.Sprintf("## Statistics\n"))
	sb.WriteString(fmt.Sprintf("- Total Models: %d\n", len(rc.Responses)))
	sb.WriteString(fmt.Sprintf("- Successful: %d\n", successCount))
	sb.WriteString(fmt.Sprintf("- Failed: %d\n\n", errorCount))

	// List all responses
	sb.WriteString("## Individual Responses\n\n")
	for modelName, resp := range rc.Responses {
		sb.WriteString(fmt.Sprintf("### %s\n", modelName))
		sb.WriteString(fmt.Sprintf("- Status: %s\n", resp.Status))
		sb.WriteString(fmt.Sprintf("- URL: %s\n", resp.URL))
		if resp.Status == "success" {
			sb.WriteString(fmt.Sprintf("- Response:\n\n%s\n\n", truncate(resp.Content, 2000)))
		} else if resp.Error != "" {
			sb.WriteString(fmt.Sprintf("- Error: %s\n\n", resp.Error))
		}
		sb.WriteString("---\n\n")
	}

	return sb.String()
}

// GenerateJSON exports all responses as JSON
func (rc *ResponseCollector) GenerateJSON() ([]byte, error) {
	rc.mu <- struct{}{}
	defer func() { <-rc.mu }()

	return json.MarshalIndent(rc.Responses, "", "  ")
}

// SaveToFile saves the summary to a file
func (rc *ResponseCollector) SaveToFile(outputDir string) error {
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return err
	}

	timestamp := time.Now().Format("20060102_150405")

	// Save markdown summary
	summary := rc.GenerateSummary()
	summaryPath := filepath.Join(outputDir, fmt.Sprintf("summary_%s.md", timestamp))
	if err := os.WriteFile(summaryPath, []byte(summary), 0644); err != nil {
		return err
	}
	log.Printf("Summary saved: %s", summaryPath)

	// Save JSON data
	jsonData, err := rc.GenerateJSON()
	if err != nil {
		return err
	}
	jsonPath := filepath.Join(outputDir, fmt.Sprintf("responses_%s.json", timestamp))
	if err := os.WriteFile(jsonPath, jsonData, 0644); err != nil {
		return err
	}
	log.Printf("Data saved: %s", jsonPath)

	return nil
}

// truncate truncates string to max length
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// debugPageContent prints debug info about page content for Copilot
func debugPageContent(page playwright.Page) {
	script := `
		(function() {
			const results = [];
			const allText = document.body.innerText || '';

			// Get all elements with text
			const allElements = Array.from(document.querySelectorAll('*'))
				.filter(el => el.innerText && el.innerText.trim().length > 30)
				.slice(0, 20);

			const elementInfos = allElements.map(el => {
				let path = [];
				let current = el;
				while (current && current !== document.body) {
					let tag = current.tagName.toLowerCase();
					if (current.id) tag += '#' + current.id;
					if (current.className && typeof current.className === 'string') {
						const classes = current.className.trim().split(/\\s+/).slice(0, 3).join('.');
						if (classes) tag += '.' + classes;
					}
					path.unshift(tag);
					current = current.parentElement;
				}
				return {
					path: path.join(' > '),
					text: el.innerText.substring(0, 200),
					length: el.innerText.length
				};
			});

			return JSON.stringify({
				totalTextLength: allText.length,
				totalTextPreview: allText.substring(0, 500),
				elements: elementInfos
			}, null, 2);
		})();
	`

	result, err := page.Evaluate(script)
	if err != nil {
		log.Printf("[Copilot DEBUG] Failed to get page content: %v", err)
		return
	}

	log.Printf("[Copilot DEBUG] Page content preview:\n%s\n", result)
}
