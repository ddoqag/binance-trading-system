package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// TestWALBasicOperations tests basic WAL logging operations
func TestWALBasicOperations(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}
	defer wal.Close()

	// Test LogOrder
	orderEntry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "LIMIT",
		Price:  50000.0,
		Size:   0.01,
		Status: "NEW",
	}
	if err := wal.LogOrder("ord_123", orderEntry); err != nil {
		t.Errorf("Failed to log order: %v", err)
	}

	// Test LogFill
	fillEntry := FillEntry{
		OrderID:   "ord_123",
		FillPrice: 50000.0,
		FillSize:  0.01,
		Fee:       0.5,
	}
	if err := wal.LogFill("ord_123", fillEntry); err != nil {
		t.Errorf("Failed to log fill: %v", err)
	}

	// Test LogCancel
	if err := wal.LogCancel("ord_123"); err != nil {
		t.Errorf("Failed to log cancel: %v", err)
	}

	// Test LogPosition
	positionEntry := PositionEntry{
		Symbol:      "BTCUSDT",
		Size:        0.01,
		AvgPrice:    50000.0,
		RealizedPnL: 0.0,
	}
	if err := wal.LogPosition(positionEntry); err != nil {
		t.Errorf("Failed to log position: %v", err)
	}

	// Verify log file was created
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFiles []string
	for _, f := range files {
		if strings.HasSuffix(f.Name(), ".log") {
			logFiles = append(logFiles, f.Name())
		}
	}

	if len(logFiles) != 1 {
		t.Errorf("Expected 1 log file, got %d", len(logFiles))
	}

	t.Logf("✓ WAL basic operations test passed")
}

// TestWALLogRotation tests log file rotation
func TestWALLogRotation(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_rotate_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL with small max entries for testing
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	// Override max entries for testing
	wal.maxEntries = 5

	// Log 10 entries (should trigger rotation)
	for i := 0; i < 10; i++ {
		orderEntry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0 + float64(i),
			Size:   0.01,
			Status: "NEW",
		}
		if err := wal.LogOrder(fmt.Sprintf("ord_%d", i), orderEntry); err != nil {
			t.Errorf("Failed to log order %d: %v", i, err)
		}
	}

	wal.Close()

	// Check that multiple log files exist
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFiles []string
	for _, f := range files {
		if strings.HasSuffix(f.Name(), ".log") {
			logFiles = append(logFiles, f.Name())
		}
	}

	if len(logFiles) < 2 {
		t.Errorf("Expected at least 2 log files after rotation, got %d", len(logFiles))
	}

	t.Logf("✓ WAL rotation test passed, created %d log files", len(logFiles))
}

// TestWALCheckpoint tests checkpoint creation and recovery
func TestWALCheckpoint(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_checkpoint_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	// Log some orders and fills
	for i := 0; i < 5; i++ {
		orderEntry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0 + float64(i),
			Size:   0.01,
			Status: "FILLED",
		}
		wal.LogOrder(fmt.Sprintf("ord_%d", i), orderEntry)
	}

	// Create checkpoint
	positions := map[string]PositionEntry{
		"BTCUSDT": {
			Symbol:      "BTCUSDT",
			Size:        0.05,
			AvgPrice:    50002.0,
			RealizedPnL: 0.0,
		},
	}

	checkpointFile, err := wal.CreateCheckpoint(positions, 10000.0, 0.0)
	if err != nil {
		t.Fatalf("Failed to create checkpoint: %v", err)
	}

	// Log more entries after checkpoint
	for i := 5; i < 10; i++ {
		orderEntry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0 + float64(i),
			Size:   0.01,
			Status: "FILLED",
		}
		wal.LogOrder(fmt.Sprintf("ord_%d", i), orderEntry)
	}

	wal.Close()

	// Verify checkpoint file exists
	if _, err := os.Stat(checkpointFile); os.IsNotExist(err) {
		t.Errorf("Checkpoint file was not created: %s", checkpointFile)
	}

	// Read checkpoint and verify content
	data, err := os.ReadFile(checkpointFile)
	if err != nil {
		t.Fatalf("Failed to read checkpoint: %v", err)
	}

	var checkpoint CheckpointEntry
	if err := json.Unmarshal(data, &checkpoint); err != nil {
		t.Fatalf("Failed to parse checkpoint: %v", err)
	}

	if checkpoint.Equity != 10000.0 {
		t.Errorf("Expected equity 10000.0, got %.2f", checkpoint.Equity)
	}

	if len(checkpoint.Positions) != 1 {
		t.Errorf("Expected 1 position, got %d", len(checkpoint.Positions))
	}

	if pos, ok := checkpoint.Positions["BTCUSDT"]; ok {
		if pos.Size != 0.05 {
			t.Errorf("Expected position size 0.05, got %.4f", pos.Size)
		}
	} else {
		t.Errorf("BTCUSDT position not found in checkpoint")
	}

	t.Logf("✓ WAL checkpoint test passed")
}

// TestWALRecovery tests state recovery from WAL logs
func TestWALRecovery(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_recovery_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL and log some entries
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	// Create initial checkpoint
	positions := map[string]PositionEntry{
		"BTCUSDT": {
			Symbol:      "BTCUSDT",
			Size:        0.0,
			AvgPrice:    0.0,
			RealizedPnL: 0.0,
		},
	}

	checkpointFile, err := wal.CreateCheckpoint(positions, 10000.0, 0.0)
	if err != nil {
		t.Fatalf("Failed to create checkpoint: %v", err)
	}

	// Simulate some trading activity
	orderEntry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "MARKET",
		Price:  0,
		Size:   0.01,
		Status: "FILLED",
	}
	wal.LogOrder("ord_1", orderEntry)

	fillEntry := FillEntry{
		OrderID:   "ord_1",
		FillPrice: 50000.0,
		FillSize:  0.01,
		Fee:       0.5,
	}
	wal.LogFill("ord_1", fillEntry)

	wal.Close()

	// Recover state
	wal2, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL for recovery: %v", err)
	}
	defer wal2.Close()

	recoveredState, err := wal2.Recovery(checkpointFile)
	if err != nil {
		t.Fatalf("Failed to recover state: %v", err)
	}

	// Verify recovered state
	if recoveredState.Equity != 10000.0 {
		t.Errorf("Expected equity 10000.0, got %.2f", recoveredState.Equity)
	}

	t.Logf("✓ WAL recovery test passed, recovered %d positions", len(recoveredState.Positions))
}

// TestWALReadLogFile tests reading log files
func TestWALReadLogFile(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_read_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL and log entries
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	entries := []struct {
		orderID string
		price   float64
	}{
		{"ord_1", 50000.0},
		{"ord_2", 50100.0},
		{"ord_3", 50200.0},
	}

	for _, e := range entries {
		orderEntry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  e.price,
			Size:   0.01,
			Status: "NEW",
		}
		wal.LogOrder(e.orderID, orderEntry)
	}

	wal.Close()

	// Read log file
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFile string
	for _, f := range files {
		if strings.HasSuffix(f.Name(), ".log") {
			logFile = filepath.Join(tempDir, f.Name())
			break
		}
	}

	if logFile == "" {
		t.Fatalf("No log file found")
	}

	// Create new WAL to use readLogFile
	wal2, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}
	defer wal2.Close()

	readEntries, err := wal2.readLogFile(logFile)
	if err != nil {
		t.Fatalf("Failed to read log file: %v", err)
	}

	if len(readEntries) != len(entries) {
		t.Errorf("Expected %d entries, got %d", len(entries), len(readEntries))
	}

	// Verify entries
	for i, entry := range readEntries {
		if entry.Type != "order" {
			t.Errorf("Entry %d: expected type 'order', got '%s'", i, entry.Type)
		}
		if entry.OrderID != entries[i].orderID {
			t.Errorf("Entry %d: expected order ID '%s', got '%s'", i, entries[i].orderID, entry.OrderID)
		}
	}

	t.Logf("✓ WAL read log file test passed, read %d entries", len(readEntries))
}

// TestWALConcurrency tests concurrent logging
func TestWALConcurrency(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_concurrent_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}
	defer wal.Close()

	// Concurrent logging from multiple goroutines
	done := make(chan bool, 10)
	for i := 0; i < 10; i++ {
		go func(id int) {
			defer func() { done <- true }()

			for j := 0; j < 10; j++ {
				orderEntry := OrderEntry{
					Symbol: "BTCUSDT",
					Side:   "BUY",
					Type:   "LIMIT",
					Price:  50000.0 + float64(id*100+j),
					Size:   0.01,
					Status: "NEW",
				}
				if err := wal.LogOrder(fmt.Sprintf("ord_%d_%d", id, j), orderEntry); err != nil {
					t.Errorf("Failed to log order: %v", err)
				}
			}
		}(i)
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}

	// Verify log file
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFile string
	for _, f := range files {
		if strings.HasSuffix(f.Name(), ".log") {
			logFile = filepath.Join(tempDir, f.Name())
			break
		}
	}

	if logFile == "" {
		t.Fatalf("No log file found")
	}

	// Count entries in log file
	data, err := os.ReadFile(logFile)
	if err != nil {
		t.Fatalf("Failed to read log file: %v", err)
	}

	lines := strings.Count(string(data), "\n")
	if lines != 100 { // 10 goroutines * 10 entries
		t.Errorf("Expected 100 log entries, got %d", lines)
	}

	t.Logf("✓ WAL concurrency test passed, logged %d entries", lines)
}

// TestWALDurability tests that logs are synced to disk
func TestWALDurability(t *testing.T) {
	// Create temp directory for test
	tempDir, err := os.MkdirTemp("", "wal_durability_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	// Create WAL
	wal, err := NewWAL(tempDir)
	if err != nil {
		t.Fatalf("Failed to create WAL: %v", err)
	}

	// Log an order
	orderEntry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "LIMIT",
		Price:  50000.0,
		Size:   0.01,
		Status: "NEW",
	}

	if err := wal.LogOrder("ord_durability", orderEntry); err != nil {
		t.Fatalf("Failed to log order: %v", err)
	}

	// Don't close WAL - simulate crash by directly reading file
	// Find log file
	files, err := os.ReadDir(tempDir)
	if err != nil {
		t.Fatalf("Failed to read temp dir: %v", err)
	}

	var logFile string
	for _, f := range files {
		if strings.HasSuffix(f.Name(), ".log") {
			logFile = filepath.Join(tempDir, f.Name())
			break
		}
	}

	if logFile == "" {
		t.Fatalf("No log file found")
	}

	// Read file directly (simulating recovery after crash)
	data, err := os.ReadFile(logFile)
	if err != nil {
		t.Fatalf("Failed to read log file: %v", err)
	}

	// Verify entry is in file (sync worked)
	if !strings.Contains(string(data), "ord_durability") {
		t.Errorf("Order not found in log file - sync may have failed")
	}

	wal.Close()
	t.Logf("✓ WAL durability test passed")
}

// BenchmarkWALAppend benchmarks WAL append operations
func BenchmarkWALAppend(b *testing.B) {
	tempDir, err := os.MkdirTemp("", "wal_bench_*")
	if err != nil {
		b.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	wal, err := NewWAL(tempDir)
	if err != nil {
		b.Fatalf("Failed to create WAL: %v", err)
	}
	defer wal.Close()

	orderEntry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "LIMIT",
		Price:  50000.0,
		Size:   0.01,
		Status: "NEW",
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		wal.LogOrder(fmt.Sprintf("ord_%d", i), orderEntry)
	}
}

// ============================================================================
// AsyncWAL Tests
// ============================================================================

// TestAsyncWALBasic tests basic AsyncWAL operations
func TestAsyncWALBasic(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "async_wal_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	config := &WALConfig{
		LogDir:        tempDir,
		MaxFileSize:   1024 * 1024, // 1MB
		MaxFiles:      5,
		BatchSize:     10,
		FlushInterval: 50 * time.Millisecond,
		AsyncWrite:    true,
		CompressOld:   false,
	}

	aw, err := NewAsyncWAL(config)
	if err != nil {
		t.Fatalf("Failed to create AsyncWAL: %v", err)
	}
	defer aw.Close()

	// Log some entries
	for i := 0; i < 5; i++ {
		entry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0 + float64(i),
			Size:   0.01,
			Status: "NEW",
		}
		if err := aw.LogOrder(fmt.Sprintf("ord_%d", i), entry); err != nil {
			t.Errorf("Failed to log order: %v", err)
		}
	}

	// Wait for flush
	time.Sleep(100 * time.Millisecond)

	// Verify stats
	stats := aw.GetStats()
	if stats["sequence"].(uint64) != 5 {
		t.Errorf("Expected sequence 5, got %d", stats["sequence"])
	}

	t.Logf("✓ AsyncWAL basic test passed")
}

// TestAsyncWALBatchFlush tests batch flushing
func TestAsyncWALBatchFlush(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "async_wal_batch_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	config := &WALConfig{
		LogDir:        tempDir,
		MaxFileSize:   1024 * 1024,
		MaxFiles:      5,
		BatchSize:     5, // Small batch size for testing
		FlushInterval: 5 * time.Second, // Long interval to test batch trigger
		AsyncWrite:    true,
		CompressOld:   false,
	}

	aw, err := NewAsyncWAL(config)
	if err != nil {
		t.Fatalf("Failed to create AsyncWAL: %v", err)
	}
	defer aw.Close()

	// Log entries to trigger batch flush
	for i := 0; i < 7; i++ {
		entry := OrderEntry{
			Symbol: "BTCUSDT",
			Side:   "BUY",
			Type:   "LIMIT",
			Price:  50000.0,
			Size:   0.01,
			Status: "NEW",
		}
		aw.LogOrder(fmt.Sprintf("ord_%d", i), entry)
	}

	// Wait for batch flush
	time.Sleep(100 * time.Millisecond)

	// Verify log file exists
	files, _ := os.ReadDir(tempDir)
	var logFiles int
	for _, f := range files {
		if filepath.Ext(f.Name()) == ".log" {
			logFiles++
		}
	}

	if logFiles == 0 {
		t.Errorf("Expected log file to be created")
	}

	t.Logf("✓ AsyncWAL batch flush test passed")
}

// TestAsyncWALChecksum tests checksum validation
func TestAsyncWALChecksum(t *testing.T) {
	tempDir, err := os.MkdirTemp("", "async_wal_checksum_test_*")
	if err != nil {
		t.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	config := &WALConfig{
		LogDir:          tempDir,
		MaxFileSize:     1024 * 1024,
		MaxFiles:        5,
		BatchSize:       10,
		FlushInterval:   50 * time.Millisecond,
		AsyncWrite:      true,
		CompressOld:     false,
		ChecksumEnabled: true,
	}

	aw, err := NewAsyncWAL(config)
	if err != nil {
		t.Fatalf("Failed to create AsyncWAL: %v", err)
	}

	// Log entry with checksum
	entry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "LIMIT",
		Price:  50000.0,
		Size:   0.01,
		Status: "NEW",
	}
	aw.LogOrder("ord_checksum", entry)

	// Force flush
	aw.Flush()
	aw.Close()

	// Verify log file contains checksum
	files, _ := os.ReadDir(tempDir)
	for _, f := range files {
		if filepath.Ext(f.Name()) == ".log" {
			data, _ := os.ReadFile(filepath.Join(tempDir, f.Name()))
			if !strings.Contains(string(data), "checksum") {
				t.Errorf("Expected checksum in log entry")
			}
		}
	}

	t.Logf("✓ AsyncWAL checksum test passed")
}

// BenchmarkAsyncWAL benchmarks AsyncWAL performance
func BenchmarkAsyncWAL(b *testing.B) {
	tempDir, err := os.MkdirTemp("", "async_wal_bench_*")
	if err != nil {
		b.Fatalf("Failed to create temp dir: %v", err)
	}
	defer os.RemoveAll(tempDir)

	config := &WALConfig{
		LogDir:        tempDir,
		MaxFileSize:   100 * 1024 * 1024,
		MaxFiles:      10,
		BatchSize:     100,
		FlushInterval: 100 * time.Millisecond,
		AsyncWrite:    true,
		CompressOld:   false,
	}

	aw, err := NewAsyncWAL(config)
	if err != nil {
		b.Fatalf("Failed to create AsyncWAL: %v", err)
	}
	defer aw.Close()

	orderEntry := OrderEntry{
		Symbol: "BTCUSDT",
		Side:   "BUY",
		Type:   "LIMIT",
		Price:  50000.0,
		Size:   0.01,
		Status: "NEW",
	}

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		aw.LogOrder(fmt.Sprintf("ord_%d", i), orderEntry)
	}

	// Wait for final flush
	aw.Flush()

	// Report stats
	stats := aw.GetStats()
	b.ReportMetric(float64(stats["sequence"].(uint64)), "entries")
}
