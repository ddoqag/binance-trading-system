// shared_memory.go
// Go 端共享内存管理
// 处理 Windows 内存映射文件

package main

import (
	"encoding/binary"
	"fmt"
	"log"
	"os"
	"sync"
	"syscall"
	"unsafe"
)

// SharedMemoryManager 共享内存管理器
type SharedMemoryManager struct {
	name       string
	size       uint64
	handle     syscall.Handle
	data       []byte
	header     *SharedMemoryHeader
	headerPtr  unsafe.Pointer
	connected  bool
	mu         sync.Mutex
}

// NewSharedMemoryManager 创建共享内存管理器
func NewSharedMemoryManager(name string, size uint64) *SharedMemoryManager {
	return &SharedMemoryManager{
		name:      name,
		size:      size,
		connected: false,
	}
}

// Initialize 初始化共享内存（创建）
func (m *SharedMemoryManager) Initialize() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.connected {
		return nil
	}

	// 我们使用临时文件来创建映射
	// 在 Windows 上，我们需要一个文件句柄
	// 这里简化处理：使用 mmap_windows.go 的 mapMemory 能力
	// 创建一个临时文件并映射
	f, err := os.CreateTemp("", "hft-shm-")
	if err != nil {
		return fmt.Errorf("create temp file failed: %w", err)
	}
	defer f.Close()

	// 确保文件大小正确
	if err := f.Truncate(int64(m.size)); err != nil {
		return fmt.Errorf("truncate failed: %w", err)
	}

	// 映射内存
	data, err := mapMemory(f, int(m.size))
	if err != nil {
		return err
	}

	// 类型转换
	m.data = data

	// 定位头部
	m.headerPtr = unsafe.Pointer(&m.data[0])
	m.header = (*SharedMemoryHeader)(m.headerPtr)

	// 初始化头部
	*m.header = *NewSharedMemoryHeader(m.size)

	// 序列化初始头部到内存
	m.header.Marshal(m.data)

	m.connected = true
	log.Printf("Shared memory initialized: name=%s, size=%d bytes", m.name, m.size)

	return nil
}

// Connect 连接到已存在的共享内存
// Note: 在当前实现中，Go 是服务端，所以不需要主动连接
func (m *SharedMemoryManager) Connect() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if m.connected {
		return nil
	}

	// 对于 Go 端，我们总是初始化，Python 客户端连接我们
	return fmt.Errorf("connect not implemented: Go is the server")
}

// GetHeader 获取头部指针
func (m *SharedMemoryManager) GetHeader() *SharedMemoryHeader {
	return m.header
}

// UpdateMarketSnapshot 更新最新市场快照
func (m *SharedMemoryManager) UpdateMarketSnapshot(snap *MarketSnapshot) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// 更新头部中的缓存快照
	m.header.LastMarketSnapshot = *snap
	m.header.LastHeartbeatGoNs = GetTimestampNs()

	// 重新序列化头部
	m.header.Marshal(m.data)
}

// UpdateAccountInfo 更新账户信息
func (m *SharedMemoryManager) UpdateAccountInfo(acc *AccountInfo) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.header.AccountInfo = *acc
	m.header.Marshal(m.data)
}

// ReadNextOrderCommand 读取下一个订单命令
// 返回 nil 表示没有新命令
func (m *SharedMemoryManager) ReadNextOrderCommand() (*OrderCommand, error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// 计算命令缓冲区偏移
	// 头部后面就是命令缓冲区
	hdrSize := unsafe.Sizeof(SharedMemoryHeader{})
	cmdOffset := uintptr(hdrSize)

	// 读取消息头
	if len(m.data) < int(cmdOffset) + 5 {
		return nil, nil
	}

	msgType := m.data[cmdOffset]
	msgSize := binary.LittleEndian.Uint32(m.data[cmdOffset+1:])

	if msgType != MsgTypeOrderCommand {
		return nil, nil
	}

	if msgSize > 1024 {
		return nil, fmt.Errorf("command too large: %d", msgSize)
	}

	// 反序列化
	cmd, _ := UnmarshalOrderCommand(m.data[cmdOffset+5 : cmdOffset+5+uintptr(msgSize)])
	return cmd, nil
}

// GetBuffer 获取完整数据缓冲区
func (m *SharedMemoryManager) GetBuffer() []byte {
	return m.data
}

// IsConnected 检查是否连接
func (m *SharedMemoryManager) IsConnected() bool {
	return m.connected
}

// Close 关闭共享内存
func (m *SharedMemoryManager) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()

	if !m.connected {
		return
	}

	if m.data != nil {
		addr := uintptr(unsafe.Pointer(&m.data[0]))
		syscall.UnmapViewOfFile(addr)
	}

	if m.handle != 0 {
		syscall.CloseHandle(m.handle)
		m.handle = 0
	}

	m.connected = false
	log.Println("Shared memory closed")
}
