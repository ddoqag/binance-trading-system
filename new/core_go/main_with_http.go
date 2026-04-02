package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"
)

// main_with_http 是增强版启动入口，包含 HTTP API 和 Prometheus Metrics
// 用法: go run main_with_http.go [symbol] [paper|live] [margin]
//
// 暴露端口:
//   - 8080: HTTP API (Risk Kernel 集成)
//   - 9090: Prometheus Metrics
func main() {
	// Parse command line args
	symbol := "btcusdt"
	if len(os.Args) > 1 {
		symbol = os.Args[1]
	}

	paperTrading := true
	if len(os.Args) > 2 && os.Args[2] == "live" {
		paperTrading = false
	}

	useMargin := false
	if len(os.Args) > 3 && os.Args[3] == "margin" {
		useMargin = true
	}

	// Create engine
	config := DefaultConfig(symbol)
	config.PaperTrading = paperTrading
	config.UseMargin = useMargin

	engine, err := NewHFTEngine(config)
	if err != nil {
		log.Fatalf("Failed to create engine: %v", err)
	}

	// Start HTTP API server (for Python Risk Kernel)
	log.Println("[MAIN] Starting HTTP API server on :8080")
	engine.StartHTTPServer(8080)

	// Start Prometheus metrics server
	log.Println("[MAIN] Starting Prometheus metrics on :9090")
	if engine.metrics != nil {
		if err := engine.metrics.Start(); err != nil {
			log.Printf("[MAIN] Failed to start metrics: %v", err)
		}
	}

	// Start engine
	if err := engine.Start(); err != nil {
		log.Fatalf("Failed to start engine: %v", err)
	}

	log.Println("[MAIN] Engine fully started. Press Ctrl+C to stop.")
	log.Println("[MAIN] Available endpoints:")
	log.Println("       - http://localhost:8080/api/v1/risk/stats")
	log.Println("       - http://localhost:8080/api/v1/system/metrics")
	log.Println("       - http://localhost:8080/api/v1/status")
	log.Println("       - http://localhost:9090/metrics")

	// Wait for interrupt
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	// Graceful shutdown
	log.Println("[MAIN] Shutting down...")
	if engine.metrics != nil {
		engine.metrics.Stop()
	}
	engine.Stop()
}
