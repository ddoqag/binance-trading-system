package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sync"
	"time"
)

/*
wal.go - Write-Ahead Logging for Disaster Recovery

Implements:
- Persistent log of all orders and position changes
- Crash recovery
- Log rotation
- State reconstruction
*/

// WALEntry represents a single log entry
type WALEntry struct {
	Timestamp int64       `json:"ts"`
	Type      string      `json:"type"`    // "order", "fill", "cancel", "position", "checkpoint"
	OrderID   string      `json:"oid,omitempty"`
	Data      interface{} `json:"data"`
}

// OrderEntry for order-related logs
type OrderEntry struct {
	Symbol    string  `json:"symbol"`
	Side      string  `json:"side"`
	Type      string  `json:"type"`
	Price     float64 `json:"price"`
	Size      float64 `json:"size"`
	Status    string  `json:"status"`
}

// FillEntry for fill-related logs
type FillEntry struct {
	OrderID   string  `json:"order_id"`
	FillPrice float64 `json:"fill_price"`
	FillSize  float64 `json:"fill_size"`
	Fee       float64 `json:"fee"`
}

// PositionEntry for position snapshots
type PositionEntry struct {
	Symbol      string  `json:"symbol"`
	Size        float64 `json:"size"`
	AvgPrice    float64 `json:"avg_price"`
	RealizedPnL float64 `json:"realized_pnl"`
}

// CheckpointEntry for periodic state snapshots
type CheckpointEntry struct {
	Timestamp   int64                  `json:"ts"`
	Positions   map[string]PositionEntry `json:"positions"`
	Equity      float64                `json:"equity"`
	DailyPnL    float64                `json:"daily_pnl"`
}

// WAL manages write-ahead logging
type WAL struct {
	logDir    string
	logFile   *os.File
	encoder   *json.Encoder
	mu        sync.Mutex
	entryCount int
	maxEntries int
}

// NewWAL creates a new WAL instance
func NewWAL(logDir string) (*WAL, error) {
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log dir: %w", err)
	}

	wal := &WAL{
		logDir:     logDir,
		maxEntries: 10000, // Rotate after 10k entries
	}

	if err := wal.openLogFile(); err != nil {
		return nil, err
	}

	return wal, nil
}

func (w *WAL) openLogFile() error {
	filename := filepath.Join(w.logDir, fmt.Sprintf("wal_%s.log", time.Now().Format("20060102_150405")))

	file, err := os.OpenFile(filename, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file: %w", err)
	}

	w.logFile = file
	w.encoder = json.NewEncoder(file)
	w.entryCount = 0

	log.Printf("[WAL] Opened log file: %s", filename)
	return nil
}

func (w *WAL) rotate() error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.entryCount < w.maxEntries {
		return nil
	}

	log.Println("[WAL] Rotating log file")

	// Close current file
	if w.logFile != nil {
		w.logFile.Close()
	}

	// Open new file
	return w.openLogFile()
}

// LogOrder logs an order event
func (w *WAL) LogOrder(orderID string, entry OrderEntry) error {
	return w.append(WALEntry{
		Timestamp: time.Now().UnixNano(),
		Type:      "order",
		OrderID:   orderID,
		Data:      entry,
	})
}

// LogFill logs a fill event
func (w *WAL) LogFill(orderID string, entry FillEntry) error {
	return w.append(WALEntry{
		Timestamp: time.Now().UnixNano(),
		Type:      "fill",
		OrderID:   orderID,
		Data:      entry,
	})
}

// LogCancel logs an order cancellation
func (w *WAL) LogCancel(orderID string) error {
	return w.append(WALEntry{
		Timestamp: time.Now().UnixNano(),
		Type:      "cancel",
		OrderID:   orderID,
	})
}

// LogPosition logs a position snapshot
func (w *WAL) LogPosition(entry PositionEntry) error {
	return w.append(WALEntry{
		Timestamp: time.Now().UnixNano(),
		Type:      "position",
		Data:      entry,
	})
}

// LogCheckpoint logs a full state checkpoint
func (w *WAL) LogCheckpoint(checkpoint CheckpointEntry) error {
	return w.append(WALEntry{
		Timestamp: checkpoint.Timestamp,
		Type:      "checkpoint",
		Data:      checkpoint,
	})
}

func (w *WAL) append(entry WALEntry) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if err := w.encoder.Encode(entry); err != nil {
		return fmt.Errorf("failed to encode log entry: %w", err)
	}

	// Sync to disk for durability
	if err := w.logFile.Sync(); err != nil {
		return fmt.Errorf("failed to sync log: %w", err)
	}

	w.entryCount++

	// Check if rotation needed
	if w.entryCount >= w.maxEntries {
		// Release lock before rotating
		w.mu.Unlock()
		err := w.rotate()
		w.mu.Lock()
		return err
	}

	return nil
}

// Close closes the WAL
func (w *WAL) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.logFile != nil {
		return w.logFile.Close()
	}
	return nil
}

// Recovery reconstructs state from WAL logs
func (w *WAL) Recovery(latestCheckpoint string) (*CheckpointEntry, error) {
	// Read checkpoint
	checkpoint, err := w.readCheckpoint(latestCheckpoint)
	if err != nil {
		return nil, fmt.Errorf("failed to read checkpoint: %w", err)
	}

	log.Printf("[RECOVERY] Starting from checkpoint at %s", time.Unix(0, checkpoint.Timestamp))

	// Replay logs after checkpoint
	entries, err := w.readLogsAfter(checkpoint.Timestamp)
	if err != nil {
		return nil, fmt.Errorf("failed to read logs: %w", err)
	}

	// Apply log entries to reconstruct state
	for _, entry := range entries {
		switch entry.Type {
		case "order":
			// Update orders tracking
			log.Printf("[RECOVERY] Replay order: %s", entry.OrderID)
		case "fill":
			// Update position based on fill
			if fillData, ok := entry.Data.(map[string]interface{}); ok {
				if symbol, ok := fillData["symbol"].(string); ok {
					if pos, exists := checkpoint.Positions[symbol]; exists {
						fillSize := fillData["fill_size"].(float64)
						fillPrice := fillData["fill_price"].(float64)

						// Update position size and average price
						oldSize := pos.Size
						if fillData["side"].(string) == "buy" {
							pos.Size += fillSize
						} else {
							pos.Size -= fillSize
						}

						// VWAP for average price
						if oldSize != 0 {
							totalValue := oldSize*pos.AvgPrice + fillSize*fillPrice
							pos.AvgPrice = totalValue / pos.Size
						} else {
							pos.AvgPrice = fillPrice
						}

						checkpoint.Positions[symbol] = pos
					}
				}
			}
		case "cancel":
			log.Printf("[RECOVERY] Replay cancel: %s", entry.OrderID)
		}
	}

	log.Printf("[RECOVERY] Reconstructed state: %d positions", len(checkpoint.Positions))
	return checkpoint, nil
}

func (w *WAL) readCheckpoint(filename string) (*CheckpointEntry, error) {
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}

	var checkpoint CheckpointEntry
	if err := json.Unmarshal(data, &checkpoint); err != nil {
		return nil, err
	}

	return &checkpoint, nil
}

func (w *WAL) readLogsAfter(timestamp int64) ([]WALEntry, error) {
	var entries []WALEntry

	// List all log files
	files, err := os.ReadDir(w.logDir)
	if err != nil {
		return nil, err
	}

	for _, file := range files {
		if file.IsDir() || filepath.Ext(file.Name()) != ".log" {
			continue
		}

		path := filepath.Join(w.logDir, file.Name())
		fileEntries, err := w.readLogFile(path)
		if err != nil {
			log.Printf("[RECOVERY] Failed to read %s: %v", path, err)
			continue
		}

		// Filter entries after checkpoint
		for _, entry := range fileEntries {
			if entry.Timestamp > timestamp {
				entries = append(entries, entry)
			}
		}
	}

	return entries, nil
}

func (w *WAL) readLogFile(path string) ([]WALEntry, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var entries []WALEntry
	decoder := json.NewDecoder(file)

	for decoder.More() {
		var entry WALEntry
		if err := decoder.Decode(&entry); err != nil {
			break
		}
		entries = append(entries, entry)
	}

	return entries, nil
}

// CreateCheckpoint creates a new checkpoint
func (w *WAL) CreateCheckpoint(positions map[string]PositionEntry, equity, dailyPnL float64) (string, error) {
	checkpoint := CheckpointEntry{
		Timestamp: time.Now().UnixNano(),
		Positions: positions,
		Equity:    equity,
		DailyPnL:  dailyPnL,
	}

	filename := filepath.Join(w.logDir, fmt.Sprintf("checkpoint_%s.json", time.Now().Format("20060102_150405")))

	data, err := json.MarshalIndent(checkpoint, "", "  ")
	if err != nil {
		return "", err
	}

	if err := os.WriteFile(filename, data, 0644); err != nil {
		return "", err
	}

	log.Printf("[WAL] Created checkpoint: %s", filename)
	return filename, nil
}
