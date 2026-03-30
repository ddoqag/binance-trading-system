//go:build windows
// +build windows

package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

var (
	kernel32         = syscall.NewLazyDLL("kernel32.dll")
	procCreateFileMappingW = kernel32.NewProc("CreateFileMappingW")
	procMapViewOfFile      = kernel32.NewProc("MapViewOfFile")
	procUnmapViewOfFile    = kernel32.NewProc("UnmapViewOfFile")
)

const (
	PAGE_READWRITE = 0x04
	FILE_MAP_ALL_ACCESS = 0xF001F
)

// mapMemory maps a file into memory (Windows implementation)
func mapMemory(fd *os.File, size int) ([]byte, error) {
	handle := syscall.Handle(fd.Fd())

	// Create file mapping
	mapping, _, err := procCreateFileMappingW.Call(
		uintptr(handle),
		0,
		uintptr(PAGE_READWRITE),
		0,
		uintptr(size),
		0,
	)
	if mapping == 0 {
		return nil, fmt.Errorf("CreateFileMapping failed: %v", err)
	}
	defer syscall.CloseHandle(syscall.Handle(mapping))

	// Map view of file
	addr, _, err := procMapViewOfFile.Call(
		mapping,
		uintptr(FILE_MAP_ALL_ACCESS),
		0,
		0,
		uintptr(size),
	)
	if addr == 0 {
		return nil, fmt.Errorf("MapViewOfFile failed: %v", err)
	}

	// Create slice from pointer
	data := (*[1 << 30]byte)(unsafe.Pointer(addr))[:size:size]

	return data, nil
}

// unmapMemory unmaps memory (Windows implementation)
func unmapMemory(data []byte) error {
	// Get pointer from slice
	ptr := unsafe.Pointer(&data[0])
	ret, _, err := procUnmapViewOfFile.Call(uintptr(ptr))
	if ret == 0 {
		return fmt.Errorf("UnmapViewOfFile failed: %v", err)
	}
	return nil
}
