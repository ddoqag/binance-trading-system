//go:build !windows
// +build !windows

package main

import (
	"os"
	"syscall"
)

// mapMemory maps a file into memory (Unix implementation)
func mapMemory(fd *os.File, size int) ([]byte, error) {
	data, err := syscall.Mmap(
		int(fd.Fd()),
		0,
		size,
		syscall.PROT_READ|syscall.PROT_WRITE,
		syscall.MAP_SHARED,
	)
	if err != nil {
		return nil, err
	}
	return data, nil
}

// unmapMemory unmaps memory (Unix implementation)
func unmapMemory(data []byte) error {
	return syscall.Munmap(data)
}
