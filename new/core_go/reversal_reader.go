package main

import (
	"fmt"
	"os"
	"sync/atomic"
	"time"
	"unsafe"
)

// ReversalSignalReader reads reversal signals from shared memory
type ReversalSignalReader struct {
	shmPath string
	fd      *os.File
	mm      *mmapAccessor
	data    []byte

	// Last read state
	lastSequence uint64
	lastReadTime time.Time

	// Statistics
	readCount  uint64
	readErrors uint64
	staleCount uint64
}

// NewReversalSignalReader creates a new reversal signal reader
func NewReversalSignalReader(shmPath string) (*ReversalSignalReader, error) {
	if shmPath == "" {
		shmPath = "/tmp/hft_reversal_shm"
	}

	// Open shared memory file
	fd, err := os.OpenFile(shmPath, os.O_RDONLY, 0644)
	if err != nil {
		return nil, fmt.Errorf("failed to open reversal shm: %w", err)
	}

	// Get file size
	stat, err := fd.Stat()
	if err != nil {
		fd.Close()
		return nil, fmt.Errorf("failed to stat file: %w", err)
	}

	minSize := int64(ReversalSignalOffset + ReversalSignalSize)
	if stat.Size() < minSize {
		fd.Close()
		return nil, fmt.Errorf("shm file too small: %d < %d", stat.Size(), minSize)
	}

	// Memory map
	data, err := mapMemory(fd, int(stat.Size()))
	if err != nil {
		fd.Close()
		return nil, fmt.Errorf("failed to mmap: %w", err)
	}

	reader := &ReversalSignalReader{
		shmPath: shmPath,
		fd:      fd,
		mm:      &mmapAccessor{data: data},
		data:    data,
	}

	return reader, nil
}

// Close closes the reader
func (r *ReversalSignalReader) Close() error {
	if r.mm != nil {
		if err := r.mm.Close(); err != nil {
			return err
		}
		r.mm = nil
	}

	if r.fd != nil {
		if err := r.fd.Close(); err != nil {
			return err
		}
		r.fd = nil
	}

	return nil
}

// ReadSignal reads the latest reversal signal from shared memory
func (r *ReversalSignalReader) ReadSignal() (*ReversalSignalSHM, bool) {
	if r.data == nil {
		return nil, false
	}

	// Read signal data from offset
	offset := ReversalSignalOffset
	if offset+ReversalSignalSize > len(r.data) {
		atomic.AddUint64(&r.readErrors, 1)
		return nil, false
	}

	// Cast memory to struct (zero-copy)
	signal := (*ReversalSignalSHM)(unsafe.Pointer(&r.data[offset]))

	// Validate magic and version
	if signal.Magic != ReversalSHMMagic {
		atomic.AddUint64(&r.readErrors, 1)
		return nil, false
	}

	if signal.Version != ReversalSHMVersion {
		atomic.AddUint64(&r.readErrors, 1)
		return nil, false
	}

	// Check if new signal
	seq := atomic.LoadUint64(&signal.Sequence)
	if seq == 0 || seq == r.lastSequence {
		return nil, false
	}

	// Check staleness (older than 1 second)
	timestamp := int64(atomic.LoadUint64(&signal.TimestampNs))
	age := time.Now().UnixNano() - timestamp
	if age > int64(time.Second) {
		atomic.AddUint64(&r.staleCount, 1)
		// Still return the signal but mark as stale
	}

	// Make a copy to avoid race conditions
	signalCopy := *signal
	r.lastSequence = seq
	r.lastReadTime = time.Now()
	atomic.AddUint64(&r.readCount, 1)

	return &signalCopy, true
}

// ReadFeatures reads the latest reversal features from shared memory (for debugging)
func (r *ReversalSignalReader) ReadFeatures() (*ReversalFeaturesSHM, bool) {
	if r.data == nil {
		return nil, false
	}

	offset := ReversalFeaturesOffset
	if offset+ReversalFeaturesSize > len(r.data) {
		return nil, false
	}

	features := (*ReversalFeaturesSHM)(unsafe.Pointer(&r.data[offset]))

	// Validate
	if features.Magic != ReversalSHMMagic {
		return nil, false
	}

	// Make a copy
	featuresCopy := *features
	return &featuresCopy, true
}

// GetStats returns reader statistics
func (r *ReversalSignalReader) GetStats() map[string]interface{} {
	return map[string]interface{}{
		"read_count":     atomic.LoadUint64(&r.readCount),
		"read_errors":    atomic.LoadUint64(&r.readErrors),
		"stale_count":    atomic.LoadUint64(&r.staleCount),
		"last_sequence":  r.lastSequence,
		"last_read_time": r.lastReadTime,
	}
}
