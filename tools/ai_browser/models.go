package main

// Region represents the region of an AI model
type Region string

const (
	RegionDomestic Region = "domestic"
	RegionOverseas Region = "overseas"
)

// AIModel represents an AI model configuration
type AIModel struct {
	Name           string
	URL            string
	RolePrompt     string
	InputSelector  string
	SubmitSelector string
	Region         Region
}

// tradingRolePromptCN is the shared quant role prompt for domestic models (Chinese).
const tradingRolePromptCN = "你是专业量化交易分析师，精通加密货币技术分析。" +
	"请严格按照以下 JSON 格式回答，不要输出任何额外内容：" +
	`{"direction":"up|down|sideways","confidence":0.0-1.0,"regime":"bull|bear|neutral|volatile","risk":"brief risk","reasoning":"brief reason"}`

// tradingRolePromptEN is the shared quant role prompt for overseas models (English).
const tradingRolePromptEN = "You are a professional quantitative trading analyst specializing in crypto technical analysis. " +
	"Reply ONLY with this exact JSON, no other text: " +
	`{"direction":"up|down|sideways","confidence":0.0-1.0,"regime":"bull|bear|neutral|volatile","risk":"brief risk","reasoning":"brief reason"}`

// GetModels returns all AI models (general purpose).
func GetModels() []AIModel {
	return []AIModel{
		{
			Name:           "ChatGPT",
			URL:            "https://chat.openai.com",
			RolePrompt:     tradingRolePromptEN,
			InputSelector:  "#prompt-textarea, textarea, [contenteditable='true']",
			SubmitSelector: "button[data-testid='send-button'], button[type='submit'], button",
			Region:         RegionOverseas,
		},
		{
			Name:           "Gemini",
			URL:            "https://gemini.google.com",
			RolePrompt:     tradingRolePromptEN,
			InputSelector:  "textarea, [contenteditable='true'], div[role='textbox'], input[type='text']",
			SubmitSelector: "button[aria-label='发送'], button[aria-label='Send'], button[title*='发送'], button",
			Region:         RegionOverseas,
		},
		{
			Name:           "Copilot",
			URL:            "https://copilot.microsoft.com",
			RolePrompt:     tradingRolePromptEN,
			InputSelector:  "textarea, [contenteditable='true'], div[role='textbox'], input[type='text']",
			SubmitSelector: "button[type='submit'], button, [aria-label='Send'], [aria-label='发送'], [title*='发送']",
			Region:         RegionOverseas,
		},
		{
			Name:           "Doubao",
			URL:            "https://www.doubao.com",
			RolePrompt:     tradingRolePromptCN,
			InputSelector:  "textarea, [contenteditable='true'], div[role='textbox'], input[type='text']",
			SubmitSelector: "button, [type='submit'], [aria-label*='发送'], [aria-label*='send']",
			Region:         RegionDomestic,
		},
		{
			Name:           "Yuanbao",
			URL:            "https://yuanbao.tencent.com",
			RolePrompt:     tradingRolePromptCN,
			InputSelector:  "textarea, [contenteditable='true'], div[role='textbox'], input[type='text']",
			SubmitSelector: "button, [type='submit'], [aria-label*='发送'], [aria-label*='send']",
			Region:         RegionDomestic,
		},
		{
			Name:           "Antafu",
			URL:            "https://chat.antafu.com/?utm_source=aihub.cn",
			RolePrompt:     tradingRolePromptCN,
			InputSelector:  "textarea, [contenteditable='true'], div[role='textbox'], input[type='text']",
			SubmitSelector: "button, [type='submit'], [aria-label*='发送'], [aria-label*='send']",
			Region:         RegionDomestic,
		},
		{
			Name:           "Grok",
			URL:            "https://grok.x.ai",
			RolePrompt:     tradingRolePromptEN,
			InputSelector:  "textarea, [contenteditable='true']",
			SubmitSelector: "button[type='submit'], button",
			Region:         RegionOverseas,
		},
	}
}

// GetModelsByRegion returns models filtered by region.
func GetModelsByRegion(region Region) []AIModel {
	var result []AIModel
	for _, m := range GetModels() {
		if m.Region == region {
			result = append(result, m)
		}
	}
	return result
}

// GetDomesticModels returns only Chinese domestic AI models.
func GetDomesticModels() []AIModel { return GetModelsByRegion(RegionDomestic) }

// GetOverseasModels returns only overseas AI models.
func GetOverseasModels() []AIModel { return GetModelsByRegion(RegionOverseas) }
