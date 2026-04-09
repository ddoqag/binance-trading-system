//! Error types for the execution engine

use thiserror::Error;

pub type Result<T> = std::result::Result<T, ExecutionError>;

#[derive(Error, Debug, Clone)]
pub enum ExecutionError {
    #[error("Order not found: {0}")]
    OrderNotFound(u64),

    #[error("Invalid order: {0}")]
    InvalidOrder(String),

    #[error("Insufficient liquidity for order {0}")]
    InsufficientLiquidity(u64),

    #[error("Price limit exceeded: {0}")]
    PriceLimitExceeded(f64),

    #[error("Ring buffer full")]
    RingBufferFull,

    #[error("Ring buffer empty")]
    RingBufferEmpty,

    #[error("IPC error: {0}")]
    IpcError(String),

    #[error("Serialization error: {0}")]
    SerializationError(String),

    #[error("Memory mapping error: {0}")]
    MemoryMapError(String),

    #[error("Engine not initialized")]
    NotInitialized,

    #[error("Engine already running")]
    AlreadyRunning,

    #[error("Shutdown in progress")]
    Shutdown,

    #[error("Internal error: {0}")]
    Internal(String),
}

impl From<std::io::Error> for ExecutionError {
    fn from(e: std::io::Error) -> Self {
        ExecutionError::Internal(e.to_string())
    }
}

impl From<serde_json::Error> for ExecutionError {
    fn from(e: serde_json::Error) -> Self {
        ExecutionError::SerializationError(e.to_string())
    }
}
