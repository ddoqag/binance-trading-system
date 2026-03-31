package main

import (
	"compress/gzip"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"io"
	"log"
	"os"
	"path/filepath"
	"sort"
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

	// Async batch writing for performance
	batchBuffer  []WALEntry
	batchSize    int
	flushTicker  *time.Ticker
	flushStop    chan struct{}
	flushMu      sync.Mutex
	batchWg      sync.WaitGroup
}

// NewWAL creates a new WAL instance
func NewWAL(logDir string) (*WAL, error) {
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log dir: %w", err)
	}

	wal := &WAL{
		logDir:      logDir,
		maxEntries:  10000, // Rotate after 10k entries
		batchBuffer: make([]WALEntry, 0, 100),
		batchSize:   100,           // Flush every 100 entries
		flushStop:   make(chan struct{}),
	}

	if err := wal.openLogFile(); err != nil {
		return nil, err
	}

	// Start background flush goroutine
	wal.startBatchFlush()

	return wal, nil
}

func (w *WAL) openLogFile() error {
	filename := filepath.Join(w.logDir, fmt.Sprintf("wal_%s.log", time.Now().Format("20060102_150405.000")))

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

// startBatchFlush starts the background batch flush goroutine
func (w *WAL) startBatchFlush() {
	w.flushTicker = time.NewTicker(100 * time.Millisecond) // Flush every 100ms
	w.batchWg.Add(1)
	go w.batchFlushLoop()
}

// batchFlushLoop periodically flushes the batch buffer
func (w *WAL) batchFlushLoop() {
	defer w.batchWg.Done()
	for {
		select {
		case <-w.flushTicker.C:
			w.flushBatch()
		case <-w.flushStop:
			// Final flush before exit
			w.flushBatch()
			return
		}
	}
}

// flushBatch writes buffered entries to disk
func (w *WAL) flushBatch() {
	w.flushMu.Lock()
	defer w.flushMu.Unlock()

	if len(w.batchBuffer) == 0 {
		return
	}

	w.mu.Lock()
	defer w.mu.Unlock()

	// Write all buffered entries
	for _, entry := range w.batchBuffer {
		if err := w.encoder.Encode(entry); err != nil {
			log.Printf("[WAL] Failed to encode entry: %v", err)
			continue
		}
		w.entryCount++
	}

	// Single fsync for entire batch (10-100x throughput improvement)
	if err := w.logFile.Sync(); err != nil {
		log.Printf("[WAL] Failed to sync: %v", err)
	}

	// Clear buffer
	w.batchBuffer = w.batchBuffer[:0]

	// Check rotation after flush
	if w.entryCount >= w.maxEntries {
		w.mu.Unlock()
		w.rotate()
		w.mu.Lock()
	}
}

func (w *WAL) append(entry WALEntry) error {
	w.flushMu.Lock()
	defer w.flushMu.Unlock()

	// Add to batch buffer
	w.batchBuffer = append(w.batchBuffer, entry)

	// Immediate flush if batch is full
	if len(w.batchBuffer) >= w.batchSize {
		w.flushMu.Unlock()
		w.flushBatch()
		w.flushMu.Lock()
	}

	return nil
}

// Flush forces immediate write of buffered entries
func (w *WAL) Flush() error {
	w.flushBatch()
	return nil
}

// Close closes the WAL
func (w *WAL) Close() error {
	// Stop batch flush goroutine
	if w.flushStop != nil {
		close(w.flushStop)
		w.batchWg.Wait()
	}

	if w.flushTicker != nil {
		w.flushTicker.Stop()
	}

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

// ============================================================================
// Enhanced WAL - Production Grade Features
// ============================================================================

// WALConfig holds configuration for the enhanced WAL
type WALConfig struct {
	LogDir           string
	MaxFileSize      int64         // Max file size before rotation
	MaxFiles         int           // Max number of log files to keep
	BatchSize        int           // Number of entries to batch before write
	FlushInterval    time.Duration // Max time to wait before flushing
	AsyncWrite       bool          // Enable async write
	CompressOld      bool          // Compress old log files
	ChecksumEnabled  bool          // Enable checksum validation
	ArchiveDir       string        // Directory for archived logs
}

// DefaultWALConfig returns default configuration
func DefaultWALConfig() *WALConfig {
	return &WALConfig{
		LogDir:          "./wal_logs",
		MaxFileSize:     100 * 1024 * 1024, // 100MB
		MaxFiles:        10,
		BatchSize:       100,
		FlushInterval:   100 * time.Millisecond,
		AsyncWrite:      true,
		CompressOld:     true,
		ChecksumEnabled: true,
		ArchiveDir:      "./wal_archive",
	}
}

// WALEntryV2 represents an enhanced log entry with checksum
type WALEntryV2 struct {
	Timestamp int64       `json:"ts"`
	Type      string      `json:"type"`
	OrderID   string      `json:"oid,omitempty"`
	Data      interface{} `json:"data"`
	Checksum  string      `json:"checksum,omitempty"`
	Sequence  uint64      `json:"seq"`
}

// CalculateChecksum computes SHA256 checksum of entry data
func (e *WALEntryV2) CalculateChecksum(hasher hash.Hash) string {
	hasher.Reset()
	data, _ := json.Marshal(e.Data)
	hasher.Write(data)
	hasher.Write([]byte(fmt.Sprintf("%d:%s:%s", e.Timestamp, e.Type, e.OrderID)))
	return hex.EncodeToString(hasher.Sum(nil))
}

// ValidateChecksum verifies entry integrity
func (e *WALEntryV2) ValidateChecksum(hasher hash.Hash) bool {
	expected := e.CalculateChecksum(hasher)
	return expected == e.Checksum
}

// AsyncWAL provides asynchronous, batched write-ahead logging
type AsyncWAL struct {
	config     *WALConfig
	logFile    *os.File
	encoder    *json.Encoder
	mu         sync.RWMutex

	// Async batching
	batch      []*WALEntryV2
	batchMu    sync.Mutex
	flushChan  chan struct{}
	stopChan   chan struct{}
	wg         sync.WaitGroup

	// Sequence tracking
	sequence   uint64
	seqMu      sync.Mutex

	// Checksum hasher
	hasher     hash.Hash

	// Current file info
	fileSize   int64
	fileIndex  int

	// Archive management
	archiveMu  sync.Mutex
}

// NewAsyncWAL creates a new asynchronous WAL
func NewAsyncWAL(config *WALConfig) (*AsyncWAL, error) {
	if config == nil {
		config = DefaultWALConfig()
	}

	// Create directories
	if err := os.MkdirAll(config.LogDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create log dir: %w", err)
	}
	if config.CompressOld {
		if err := os.MkdirAll(config.ArchiveDir, 0755); err != nil {
			return nil, fmt.Errorf("failed to create archive dir: %w", err)
		}
	}

	aw := &AsyncWAL{
		config:    config,
		batch:     make([]*WALEntryV2, 0, config.BatchSize),
		flushChan: make(chan struct{}, 1),
		stopChan:  make(chan struct{}),
		hasher:    sha256.New(),
	}

	if err := aw.openLogFile(); err != nil {
		return nil, err
	}

	// Start background flush goroutine
	if config.AsyncWrite {
		aw.wg.Add(1)
		go aw.flushLoop()
	}

	// Start archive cleanup goroutine
	if config.CompressOld {
		aw.wg.Add(1)
		go aw.archiveLoop()
	}

	log.Printf("[AsyncWAL] Initialized with batch size %d, flush interval %v",
		config.BatchSize, config.FlushInterval)
	return aw, nil
}

// openLogFile opens a new log file
func (aw *AsyncWAL) openLogFile() error {
	filename := filepath.Join(
		aw.config.LogDir,
		fmt.Sprintf("wal_v2_%s_%03d.log", time.Now().Format("20060102_150405"), aw.fileIndex),
	)

	file, err := os.OpenFile(filename, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return fmt.Errorf("failed to open log file: %w", err)
	}

	if aw.logFile != nil {
		aw.logFile.Close()
	}

	aw.logFile = file
	aw.encoder = json.NewEncoder(file)
	aw.fileSize = 0
	aw.fileIndex++

	log.Printf("[AsyncWAL] Opened log file: %s", filename)
	return nil
}

// NextSequence returns the next sequence number
func (aw *AsyncWAL) NextSequence() uint64 {
	aw.seqMu.Lock()
	defer aw.seqMu.Unlock()
	aw.sequence++
	return aw.sequence
}

// LogEntry asynchronously logs an entry
func (aw *AsyncWAL) LogEntry(entryType string, orderID string, data interface{}) error {
	entry := &WALEntryV2{
		Timestamp: time.Now().UnixNano(),
		Type:      entryType,
		OrderID:   orderID,
		Data:      data,
		Sequence:  aw.NextSequence(),
	}

	if aw.config.ChecksumEnabled {
		entry.Checksum = entry.CalculateChecksum(aw.hasher)
	}

	aw.batchMu.Lock()
	aw.batch = append(aw.batch, entry)
	shouldFlush := len(aw.batch) >= aw.config.BatchSize
	aw.batchMu.Unlock()

	if shouldFlush {
		select {
		case aw.flushChan <- struct{}{}:
		default:
		}
	}

	return nil
}

// LogOrder logs an order event
func (aw *AsyncWAL) LogOrder(orderID string, entry OrderEntry) error {
	return aw.LogEntry("order", orderID, entry)
}

// LogFill logs a fill event
func (aw *AsyncWAL) LogFill(orderID string, entry FillEntry) error {
	return aw.LogEntry("fill", orderID, entry)
}

// LogCancel logs a cancellation
func (aw *AsyncWAL) LogCancel(orderID string) error {
	return aw.LogEntry("cancel", orderID, nil)
}

// LogPosition logs a position snapshot
func (aw *AsyncWAL) LogPosition(entry PositionEntry) error {
	return aw.LogEntry("position", "", entry)
}

// LogCheckpoint logs a checkpoint
func (aw *AsyncWAL) LogCheckpoint(checkpoint CheckpointEntry) error {
	return aw.LogEntry("checkpoint", "", checkpoint)
}

// flushLoop periodically flushes the batch
func (aw *AsyncWAL) flushLoop() {
	defer aw.wg.Done()
	ticker := time.NewTicker(aw.config.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			aw.Flush()
		case <-aw.flushChan:
			aw.Flush()
		case <-aw.stopChan:
			aw.Flush()
			return
		}
	}
}

// Flush writes all pending entries to disk
func (aw *AsyncWAL) Flush() error {
	aw.batchMu.Lock()
	if len(aw.batch) == 0 {
		aw.batchMu.Unlock()
		return nil
	}

	batch := aw.batch
	aw.batch = make([]*WALEntryV2, 0, aw.config.BatchSize)
	aw.batchMu.Unlock()

	aw.mu.Lock()
	defer aw.mu.Unlock()

	// Check if rotation needed
	if aw.fileSize >= aw.config.MaxFileSize {
		if err := aw.rotate(); err != nil {
			return fmt.Errorf("failed to rotate log: %w", err)
		}
	}

	// Write entries
	for _, entry := range batch {
		if err := aw.encoder.Encode(entry); err != nil {
			return fmt.Errorf("failed to encode entry: %w", err)
		}
	}

	// Sync to disk
	if err := aw.logFile.Sync(); err != nil {
		return fmt.Errorf("failed to sync: %w", err)
	}

	aw.fileSize += int64(len(batch) * 200) // Approximate size

	log.Printf("[AsyncWAL] Flushed %d entries", len(batch))
	return nil
}

// rotate closes current file and opens a new one
func (aw *AsyncWAL) rotate() error {
	log.Println("[AsyncWAL] Rotating log file")

	if aw.logFile != nil {
		aw.logFile.Close()

		// Compress old file if enabled
		if aw.config.CompressOld {
			go aw.compressOldLog(aw.logFile.Name())
		}
	}

	return aw.openLogFile()
}

// compressOldLog compresses an old log file
func (aw *AsyncWAL) compressOldLog(filepath string) {
	aw.archiveMu.Lock()
	defer aw.archiveMu.Unlock()

	input, err := os.Open(filepath)
	if err != nil {
		log.Printf("[AsyncWAL] Failed to open log for compression: %v", err)
		return
	}
	defer input.Close()

	archivePath := filepath + ".gz"
	output, err := os.Create(archivePath)
	if err != nil {
		log.Printf("[AsyncWAL] Failed to create archive: %v", err)
		return
	}
	defer output.Close()

	gzipWriter := gzip.NewWriter(output)
	defer gzipWriter.Close()

	if _, err := io.Copy(gzipWriter, input); err != nil {
		log.Printf("[AsyncWAL] Failed to compress: %v", err)
		return
	}

	// Remove original file after successful compression
	input.Close()
	os.Remove(filepath)

	log.Printf("[AsyncWAL] Compressed %s", archivePath)
}

// archiveLoop periodically cleans up old archives
func (aw *AsyncWAL) archiveLoop() {
	defer aw.wg.Done()
	ticker := time.NewTicker(time.Hour)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			aw.cleanupOldArchives()
		case <-aw.stopChan:
			return
		}
	}
}

// cleanupOldArchives removes old compressed log files
func (aw *AsyncWAL) cleanupOldArchives() {
	files, err := os.ReadDir(aw.config.ArchiveDir)
	if err != nil {
		return
	}

	// Sort by modification time
	type fileInfo struct {
		name    string
		modTime time.Time
	}

	var archives []fileInfo
	for _, f := range files {
		if filepath.Ext(f.Name()) == ".gz" {
			info, _ := f.Info()
			if info != nil {
				archives = append(archives, fileInfo{f.Name(), info.ModTime()})
			}
		}
	}

	sort.Slice(archives, func(i, j int) bool {
		return archives[i].modTime.After(archives[j].modTime)
	})

	// Remove old files exceeding MaxFiles
	if len(archives) > aw.config.MaxFiles {
		for _, archive := range archives[aw.config.MaxFiles:] {
			path := filepath.Join(aw.config.ArchiveDir, archive.name)
			os.Remove(path)
			log.Printf("[AsyncWAL] Removed old archive: %s", archive.name)
		}
	}
}

// Close gracefully shuts down the WAL
func (aw *AsyncWAL) Close() error {
	close(aw.stopChan)
	aw.wg.Wait()

	aw.mu.Lock()
	defer aw.mu.Unlock()

	// Final flush
	aw.Flush()

	if aw.logFile != nil {
		return aw.logFile.Close()
	}
	return nil
}

// GetStats returns WAL statistics
func (aw *AsyncWAL) GetStats() map[string]interface{} {
	aw.batchMu.Lock()
	batchSize := len(aw.batch)
	aw.batchMu.Unlock()

	aw.seqMu.Lock()
	sequence := aw.sequence
	aw.seqMu.Unlock()

	return map[string]interface{}{
		"batch_size":      batchSize,
		"sequence":        sequence,
		"file_size":       aw.fileSize,
		"file_index":      aw.fileIndex,
		"async_enabled":   aw.config.AsyncWrite,
		"compression":     aw.config.CompressOld,
	}
}

// RecoveryV2 recovers state from WAL logs with validation
func (aw *AsyncWAL) RecoveryV2(checkpointFile string) (*CheckpointEntry, []*WALEntryV2, error) {
	// Read checkpoint
	checkpoint, err := aw.readCheckpoint(checkpointFile)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read checkpoint: %w", err)
	}

	// Read all log entries after checkpoint
	entries, err := aw.readAllLogsAfter(checkpoint.Timestamp)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to read logs: %w", err)
	}

	// Validate checksums
	validEntries := make([]*WALEntryV2, 0, len(entries))
	corruptedCount := 0

	for _, entry := range entries {
		if aw.config.ChecksumEnabled && entry.Checksum != "" {
			if !entry.ValidateChecksum(aw.hasher) {
				corruptedCount++
				log.Printf("[RecoveryV2] Corrupted entry detected: seq=%d", entry.Sequence)
				continue
			}
		}
		validEntries = append(validEntries, entry)
	}

	if corruptedCount > 0 {
		log.Printf("[RecoveryV2] Warning: %d corrupted entries skipped", corruptedCount)
	}

	return checkpoint, validEntries, nil
}

func (aw *AsyncWAL) readCheckpoint(filename string) (*CheckpointEntry, error) {
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

func (aw *AsyncWAL) readAllLogsAfter(timestamp int64) ([]*WALEntryV2, error) {
	var entries []*WALEntryV2

	// List all log files (including compressed)
	files, err := os.ReadDir(aw.config.LogDir)
	if err != nil {
		return nil, err
	}

	// Also check archive dir
	if aw.config.CompressOld {
		archiveFiles, _ := os.ReadDir(aw.config.ArchiveDir)
		for _, f := range archiveFiles {
			files = append(files, f)
		}
	}

	for _, file := range files {
		if file.IsDir() {
			continue
		}

		var fileEntries []*WALEntryV2
		var err error

		if filepath.Ext(file.Name()) == ".gz" {
			fileEntries, err = aw.readCompressedLogFile(filepath.Join(aw.config.ArchiveDir, file.Name()))
		} else if filepath.Ext(file.Name()) == ".log" {
			fileEntries, err = aw.readLogFileV2(filepath.Join(aw.config.LogDir, file.Name()))
		} else {
			continue
		}

		if err != nil {
			log.Printf("[RecoveryV2] Failed to read %s: %v", file.Name(), err)
			continue
		}

		// Filter entries after checkpoint
		for _, entry := range fileEntries {
			if entry.Timestamp > timestamp {
				entries = append(entries, entry)
			}
		}
	}

	// Sort by sequence number
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Sequence < entries[j].Sequence
	})

	return entries, nil
}

func (aw *AsyncWAL) readLogFileV2(path string) ([]*WALEntryV2, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var entries []*WALEntryV2
	decoder := json.NewDecoder(file)

	for decoder.More() {
		var entry WALEntryV2
		if err := decoder.Decode(&entry); err != nil {
			break
		}
		entries = append(entries, &entry)
	}

	return entries, nil
}

func (aw *AsyncWAL) readCompressedLogFile(path string) ([]*WALEntryV2, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	gzipReader, err := gzip.NewReader(file)
	if err != nil {
		return nil, err
	}
	defer gzipReader.Close()

	var entries []*WALEntryV2
	decoder := json.NewDecoder(gzipReader)

	for decoder.More() {
		var entry WALEntryV2
		if err := decoder.Decode(&entry); err != nil {
			break
		}
		entries = append(entries, &entry)
	}

	return entries, nil
}
