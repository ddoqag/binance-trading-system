//! Standalone Rust execution engine binary
//!
//! Run this for high-performance execution without Python.

use std::sync::Arc;
use std::time::Duration;
use tokio::time::interval;
use tracing::{info, error};

// Import from lib
use rust_execution::{ExecutionEngine, EngineConfig};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize logging
    tracing_subscriber::fmt::init();

    info!("Starting Rust Execution Engine (standalone)");

    // Create configuration
    let config = EngineConfig {
        ring_buffer_capacity: 65536,
        ipc_buffer_size: 16 * 1024 * 1024,
        ipc_path: "/tmp/rust_execution".to_string(),
        tick_sizes: [
            ("BTCUSDT".to_string(), 0.01),
            ("ETHUSDT".to_string(), 0.01),
            ("BNBUSDT".to_string(), 0.01),
        ].into_iter().collect(),
        lot_sizes: [
            ("BTCUSDT".to_string(), 0.0001),
            ("ETHUSDT".to_string(), 0.0001),
            ("BNBUSDT".to_string(), 0.001),
        ].into_iter().collect(),
        enable_ipc: true,
    };

    // Create and start engine
    let engine = ExecutionEngine::new(config)?;
    engine.start()?;

    info!("Engine started successfully");

    // Run heartbeat and stats printing
    let mut ticker = interval(Duration::from_secs(5));

    loop {
        tokio::select! {
            _ = ticker.tick() => {
                if !engine.is_running() {
                    info!("Engine stopped, exiting");
                    break;
                }

                // Print stats
                let stats = engine.get_stats();
                info!(
                    "Stats: orders={}/{}, fills={}, volume={:.4}",
                    stats.orders_executed,
                    stats.orders_received,
                    stats.fills_generated,
                    stats.total_volume
                );

                // Process IPC
                if let Err(e) = engine.process_ipc() {
                    error!("IPC error: {}", e);
                }
            }
            _ = tokio::signal::ctrl_c() => {
                info!("Received Ctrl+C, shutting down");
                engine.stop()?;
                break;
            }
        }
    }

    info!("Rust Execution Engine exited");
    Ok(())
}
