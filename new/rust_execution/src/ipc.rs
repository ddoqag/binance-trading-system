//! Inter-process communication with Go engine
//!
//! Shared memory protocol for zero-copy communication between Rust and Go.

use crate::error::{ExecutionError, Result};
use crate::types::{Order, Fill, Tick, Symbol};

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use memmap2::{MmapMut, MmapOptions};
use std::fs::OpenOptions;
use std::path::Path;

/// Shared memory header
#[repr(C, align(4096))]
pub struct ShmHeader {
    /// Magic number: 0x52555445 ("RUST")
    pub magic: AtomicU64,
    /// Version
    pub version: AtomicU64,
    /// Sequence number for synchronization
    pub sequence: AtomicU64,
    /// Flags
    pub flags: AtomicU64,
    /// Write position
    pub write_pos: AtomicU64,
    /// Read position
    pub read_pos: AtomicU64,
    /// Buffer size
    pub buffer_size: AtomicU64,
    /// Padding to cache line
    _padding: [u8; 64 - 56],
}

impl ShmHeader {
    const MAGIC: u64 = 0x52555445; // "RUST"
    const VERSION: u64 = 1;

    pub fn new(buffer_size: usize) -> Self {
        Self {
            magic: AtomicU64::new(Self::MAGIC),
            version: AtomicU64::new(Self::VERSION),
            sequence: AtomicU64::new(0),
            flags: AtomicU64::new(0),
            write_pos: AtomicU64::new(0),
            read_pos: AtomicU64::new(0),
            buffer_size: AtomicU64::new(buffer_size as u64),
            _padding: [0; 8],
        }
    }

    pub fn is_valid(&self) -> bool {
        self.magic.load(Ordering::Relaxed) == Self::MAGIC
            && self.version.load(Ordering::Relaxed) == Self::VERSION
    }
}

/// Message type
#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MessageType {
    Heartbeat = 0,
    Order = 1,
    Cancel = 2,
    Fill = 3,
    Tick = 4,
    Book = 5,
    Control = 6,
}

/// Message header
#[repr(C)]
#[derive(Debug, Clone)]
pub struct MessageHeader {
    pub msg_type: u8,
    pub flags: u8,
    pub padding: u16,
    pub size: u32,
    pub timestamp_ns: u64,
    pub sequence: u64,
}

impl MessageHeader {
    pub const SIZE: usize = std::mem::size_of::<Self>();

    pub fn new(msg_type: MessageType, size: usize) -> Self {
        Self {
            msg_type: msg_type as u8,
            flags: 0,
            padding: 0,
            size: size as u32,
            timestamp_ns: crate::types::current_timestamp_ns(),
            sequence: 0,
        }
    }
}

/// IPC channel using shared memory
pub struct IpcChannel {
    mmap: MmapMut,
    header: *mut ShmHeader,
    buffer_offset: usize,
}

unsafe impl Send for IpcChannel {}
unsafe impl Sync for IpcChannel {}

impl IpcChannel {
    const HEADER_SIZE: usize = std::mem::size_of::<ShmHeader>();

    /// Create or open a shared memory channel
    pub fn create_or_open<P: AsRef<Path>>(path: P, size: usize) -> Result<Self> {
        let total_size = size + Self::HEADER_SIZE;

        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&path)?;

        // Set file size
        file.set_len(total_size as u64)?;

        let mut mmap = unsafe { MmapOptions::new().map_mut(&file)? };
        let header = mmap.as_mut_ptr() as *mut ShmHeader;

        // Check if initialized
        let is_new = unsafe { (*header).magic.load(Ordering::Relaxed) != ShmHeader::MAGIC };

        if is_new {
            // Initialize header
            unsafe {
                std::ptr::write(header, ShmHeader::new(size));
            }
        }

        Ok(Self {
            mmap,
            header,
            buffer_offset: Self::HEADER_SIZE,
        })
    }

    /// Get header reference
    fn header(&self) -> &ShmHeader {
        unsafe { &*self.header }
    }

    /// Get buffer size
    pub fn buffer_size(&self) -> usize {
        self.header().buffer_size.load(Ordering::Relaxed) as usize
    }

    /// Write a message
    pub fn write_message(&mut self, msg_type: MessageType, data: &[u8]) -> Result<()> {
        let buffer_size = self.buffer_size();

        let msg_header = MessageHeader::new(msg_type, data.len());
        let total_size = MessageHeader::SIZE + data.len();

        // Check space - load positions directly to avoid borrow issues
        let write_pos = self.header().write_pos.load(Ordering::Relaxed) as usize;
        let read_pos = self.header().read_pos.load(Ordering::Acquire);

        let available = if write_pos >= read_pos as usize {
            buffer_size - write_pos + read_pos as usize
        } else {
            read_pos as usize - write_pos
        };

        if available < total_size + 8 {
            return Err(ExecutionError::RingBufferFull);
        }

        // Write message header
        let offset = self.buffer_offset + write_pos;
        unsafe {
            let ptr = self.mmap.as_ptr().add(offset) as *mut MessageHeader;
            std::ptr::write(ptr, msg_header);
        }

        // Write data
        let data_offset = offset + MessageHeader::SIZE;
        unsafe {
            std::ptr::copy_nonoverlapping(
                data.as_ptr(),
                self.mmap.as_mut_ptr().add(data_offset),
                data.len(),
            );
        }

        // Update write position - reload header to avoid borrow issues
        let new_pos = (write_pos + total_size) % buffer_size;
        self.header().write_pos.store(new_pos as u64, Ordering::Release);
        self.header().sequence.fetch_add(1, Ordering::Release);

        Ok(())
    }

    /// Read a message (non-blocking)
    pub fn read_message(&self) -> Result<Option<(MessageType, Vec<u8>)>> {
        let header = self.header();
        let buffer_size = self.buffer_size();

        let write_pos = header.write_pos.load(Ordering::Acquire) as usize;
        let read_pos = header.read_pos.load(Ordering::Relaxed) as usize;

        if read_pos == write_pos {
            return Ok(None); // Empty
        }

        // Read message header
        let offset = self.buffer_offset + read_pos;
        let msg_header = unsafe {
            let ptr = self.mmap.as_ptr().add(offset) as *const MessageHeader;
            std::ptr::read(ptr)
        };

        let total_size = MessageHeader::SIZE + msg_header.size as usize;

        // Read data
        let data_offset = offset + MessageHeader::SIZE;
        let data = unsafe {
            let mut buf = vec![0u8; msg_header.size as usize];
            std::ptr::copy_nonoverlapping(
                self.mmap.as_ptr().add(data_offset),
                buf.as_mut_ptr(),
                msg_header.size as usize,
            );
            buf
        };

        // Update read position
        let new_pos = (read_pos + total_size) % buffer_size;
        header.read_pos.store(new_pos as u64, Ordering::Release);

        let msg_type = match msg_header.msg_type {
            0 => MessageType::Heartbeat,
            1 => MessageType::Order,
            2 => MessageType::Cancel,
            3 => MessageType::Fill,
            4 => MessageType::Tick,
            5 => MessageType::Book,
            6 => MessageType::Control,
            _ => return Err(ExecutionError::InvalidOrder("Unknown message type".to_string())),
        };

        Ok(Some((msg_type, data)))
    }
}

/// Bidirectional IPC connection
pub struct IpcConnection {
    to_go: IpcChannel,
    from_go: IpcChannel,
}

impl IpcConnection {
    /// Create bidirectional connection
    pub fn create<P: AsRef<Path>>(base_path: P, buffer_size: usize) -> Result<Self> {
        let to_go_path = base_path.as_ref().join("rust_to_go.shm");
        let from_go_path = base_path.as_ref().join("go_to_rust.shm");

        Ok(Self {
            to_go: IpcChannel::create_or_open(to_go_path, buffer_size)?,
            from_go: IpcChannel::create_or_open(from_go_path, buffer_size)?,
        })
    }

    /// Send order to Go
    pub fn send_order(&mut self, order: &Order) -> Result<()> {
        let data = serde_json::to_vec(order)?;
        self.to_go.write_message(MessageType::Order, &data)
    }

    /// Send cancel to Go
    pub fn send_cancel(&mut self, order_id: u64) -> Result<()> {
        let data = order_id.to_le_bytes().to_vec();
        self.to_go.write_message(MessageType::Cancel, &data)
    }

    /// Receive fills from Go
    pub fn receive_fills(&self) -> Result<Vec<Fill>> {
        let mut fills = Vec::new();
        while let Some((msg_type, data)) = self.from_go.read_message()? {
            match msg_type {
                MessageType::Fill => {
                    let fill: Fill = serde_json::from_slice(&data)?;
                    fills.push(fill);
                }
                MessageType::Tick => {
                    // Process tick
                }
                _ => {}
            }
        }
        Ok(fills)
    }

    /// Send heartbeat
    pub fn send_heartbeat(&mut self) -> Result<()> {
        self.to_go.write_message(MessageType::Heartbeat, b"")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env::temp_dir;

    #[test]
    fn test_ipc_basic() {
        let path = temp_dir().join("test_ipc.shm");
        let _ = std::fs::remove_file(&path);

        let mut channel = IpcChannel::create_or_open(&path, 1024 * 1024).unwrap();

        // Write message
        channel.write_message(MessageType::Order, b"test data").unwrap();

        // Read message
        let (msg_type, data) = channel.read_message().unwrap().unwrap();
        assert_eq!(msg_type, MessageType::Order);
        assert_eq!(data, b"test data");

        let _ = std::fs::remove_file(&path);
    }
}
