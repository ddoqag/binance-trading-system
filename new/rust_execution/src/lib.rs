//! Rust Execution Engine
//!
//! High-performance execution engine for HFT trading.
//! Provides zero-copy order book, lock-free ring buffer, and ultra-low latency matching.

pub mod engine;
pub mod error;
pub mod ffi;
pub mod ipc;
pub mod matcher;
pub mod order_book;
pub mod ring_buffer;
pub mod types;

pub use engine::{ExecutionEngine, EngineConfig, EngineStats};
pub use error::{ExecutionError, Result};
pub use order_book::{Level, OrderBook};
pub use types::*;

use std::sync::atomic::{AtomicU64, Ordering};

/// Global order ID generator
static ORDER_ID_COUNTER: AtomicU64 = AtomicU64::new(1);

/// Generate unique order ID
#[inline]
pub fn generate_order_id() -> u64 {
    ORDER_ID_COUNTER.fetch_add(1, Ordering::Relaxed)
}

/// Initialize the Rust execution engine
pub fn init() {
    env_logger::init();
    tracing_subscriber::fmt::init();
}

// The ffi module (with #[pymodule]) is the Python module entry point when 'python' feature is enabled