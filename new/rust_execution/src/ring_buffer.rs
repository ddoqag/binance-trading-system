//! Lock-free Ring Buffer for inter-thread communication
//!
//! Single-producer single-consumer (SPSC) lock-free ring buffer
//! optimized for ultra-low latency message passing.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::alloc::{self, Layout};
use std::ptr::NonNull;

use crate::error::{ExecutionError, Result};

/// Cache line size (64 bytes on x86_64)
const CACHE_LINE: usize = 64;

/// Pad to cache line to prevent false sharing
#[repr(C, align(64))]
struct PaddedU64 {
    value: AtomicU64,
}

impl PaddedU64 {
    fn new(value: u64) -> Self {
        Self {
            value: AtomicU64::new(value),
        }
    }
}

/// Lock-free SPSC ring buffer
pub struct RingBuffer<T> {
    buffer: NonNull<T>,
    capacity: usize,
    mask: usize,

    // Separate cache lines for head/tail to prevent false sharing
    head: PaddedU64,  // Write position (producer)
    tail: PaddedU64,  // Read position (consumer)
}

unsafe impl<T: Send> Send for RingBuffer<T> {}
unsafe impl<T: Send> Sync for RingBuffer<T> {}

impl<T> RingBuffer<T> {
    /// Create a new ring buffer with capacity (must be power of 2)
    pub fn new(capacity: usize) -> Result<Self> {
        if capacity == 0 || (capacity & (capacity - 1)) != 0 {
            return Err(ExecutionError::InvalidOrder(
                "Capacity must be power of 2".to_string()
            ));
        }

        let layout = Layout::array::<T>(capacity)
            .map_err(|_| ExecutionError::Internal("Layout error".to_string()))?;

        let ptr = unsafe { alloc::alloc(layout) as *mut T };
        let buffer = NonNull::new(ptr)
            .ok_or_else(|| ExecutionError::Internal("Allocation failed".to_string()))?;

        Ok(Self {
            buffer,
            capacity,
            mask: capacity - 1,
            head: PaddedU64::new(0),
            tail: PaddedU64::new(0),
        })
    }

    /// Get capacity
    #[inline]
    pub fn capacity(&self) -> usize {
        self.capacity
    }

    /// Get current size
    #[inline]
    pub fn len(&self) -> usize {
        let head = self.head.value.load(Ordering::Acquire);
        let tail = self.tail.value.load(Ordering::Acquire);
        (head - tail) as usize
    }

    /// Check if empty
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Check if full
    #[inline]
    pub fn is_full(&self) -> bool {
        self.len() == self.capacity
    }

    /// Try to push an item (non-blocking)
    #[inline]
    pub fn try_push(&self, item: T) -> Result<()> {
        let head = self.head.value.load(Ordering::Relaxed);
        let tail = self.tail.value.load(Ordering::Acquire);

        // Check if full
        if (head - tail) as usize >= self.capacity {
            return Err(ExecutionError::RingBufferFull);
        }

        // Write item
        unsafe {
            let index = (head as usize) & self.mask;
            self.buffer.as_ptr().add(index).write(item);
        }

        // Update head
        self.head.value.store(head + 1, Ordering::Release);
        Ok(())
    }

    /// Try to pop an item (non-blocking)
    #[inline]
    pub fn try_pop(&self) -> Result<T> {
        let tail = self.tail.value.load(Ordering::Relaxed);
        let head = self.head.value.load(Ordering::Acquire);

        // Check if empty
        if head == tail {
            return Err(ExecutionError::RingBufferEmpty);
        }

        // Read item
        let item = unsafe {
            let index = (tail as usize) & self.mask;
            self.buffer.as_ptr().add(index).read()
        };

        // Update tail
        self.tail.value.store(tail + 1, Ordering::Release);
        Ok(item)
    }

    /// Get available space
    #[inline]
    pub fn available(&self) -> usize {
        self.capacity - self.len()
    }
}

impl<T> Drop for RingBuffer<T> {
    fn drop(&mut self) {
        // Drop remaining items
        while self.try_pop().is_ok() {}

        // Free buffer
        let layout = Layout::array::<T>(self.capacity).unwrap();
        unsafe {
            alloc::dealloc(self.buffer.as_ptr() as *mut u8, layout);
        }
    }
}

/// Thread-safe handle for producer
pub struct Producer<T> {
    buffer: Arc<RingBuffer<T>>,
}

impl<T> Producer<T> {
    #[inline]
    pub fn try_push(&self, item: T) -> Result<()> {
        self.buffer.try_push(item)
    }

    #[inline]
    pub fn is_full(&self) -> bool {
        self.buffer.is_full()
    }

    #[inline]
    pub fn available(&self) -> usize {
        self.buffer.available()
    }
}

/// Thread-safe handle for consumer
pub struct Consumer<T> {
    buffer: Arc<RingBuffer<T>>,
}

impl<T> Consumer<T> {
    #[inline]
    pub fn try_pop(&self) -> Result<T> {
        self.buffer.try_pop()
    }

    #[inline]
    pub fn is_empty(&self) -> bool {
        self.buffer.is_empty()
    }
}

/// Create a new SPSC ring buffer pair
pub fn channel<T>(capacity: usize) -> Result<(Producer<T>, Consumer<T>)> {
    let buffer = Arc::new(RingBuffer::new(capacity)?);
    Ok((
        Producer { buffer: buffer.clone() },
        Consumer { buffer },
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ring_buffer_basic() {
        let rb = RingBuffer::<i32>::new(16).unwrap();

        assert!(rb.is_empty());
        assert_eq!(rb.len(), 0);

        rb.try_push(42).unwrap();
        assert_eq!(rb.len(), 1);

        let val = rb.try_pop().unwrap();
        assert_eq!(val, 42);
        assert!(rb.is_empty());
    }

    #[test]
    fn test_ring_buffer_full() {
        let rb = RingBuffer::<i32>::new(4).unwrap();

        rb.try_push(1).unwrap();
        rb.try_push(2).unwrap();
        rb.try_push(3).unwrap();
        rb.try_push(4).unwrap();

        assert!(rb.is_full());
        assert!(rb.try_push(5).is_err());
    }

    #[test]
    fn test_channel() {
        let (prod, cons) = channel::<i32>(16).unwrap();

        prod.try_push(1).unwrap();
        prod.try_push(2).unwrap();

        assert_eq!(cons.try_pop().unwrap(), 1);
        assert_eq!(cons.try_pop().unwrap(), 2);
    }
}
