//go:build !http_server
// +build !http_server

package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"
)

// main is the entry point for the Go HFT Engine (default version without HTTP)
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

	// Start engine
	if err := engine.Start(); err != nil {
		log.Fatalf("Failed to start engine: %v", err)
	}

	// Wait for interrupt
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	<-sigChan

	// Graceful shutdown
	engine.Stop()
}
