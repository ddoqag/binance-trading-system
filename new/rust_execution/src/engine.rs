//! Core execution engine
//!
//! Main entry point for the Rust execution engine.
//! Integrates order matching, ring buffer IPC, and shared memory with Go.

use crate::error::{ExecutionError, Result};
use crate::matcher::{MatcherManager, OrderMatcher};
use crate::order_book::{OrderBook, OrderBookManager};
use crate::ring_buffer::{channel, Consumer, Producer};
use crate::types::{Fill, Order, Position, Symbol, Tick};
use crate::ipc::IpcConnection;

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use parking_lot::RwLock;
use tokio::sync::mpsc;
use tokio::time::interval;
use tracing::{debug, error, info, warn};

/// Engine configuration
#[derive(Debug, Clone)]
pub struct EngineConfig {
    /// Ring buffer capacity
    pub ring_buffer_capacity: usize,
    /// IPC buffer size
    pub ipc_buffer_size: usize,
    /// IPC path
    pub ipc_path: String,
    /// Tick size by symbol
    pub tick_sizes: HashMap<String, f64>,
    /// Lot size by symbol
    pub lot_sizes: HashMap<String, f64>,
    /// Enable IPC
    pub enable_ipc: bool,
}

impl Default for EngineConfig {
    fn default() -> Self {
        let mut tick_sizes = HashMap::new();
        tick_sizes.insert("BTCUSDT".to_string(), 0.01);
        tick_sizes.insert("ETHUSDT".to_string(), 0.01);

        let mut lot_sizes = HashMap::new();
        lot_sizes.insert("BTCUSDT".to_string(), 0.0001);
        lot_sizes.insert("ETHUSDT".to_string(), 0.0001);

        Self {
            ring_buffer_capacity: 65536,
            ipc_buffer_size: 16 * 1024 * 1024, // 16MB
            ipc_path: "/tmp/rust_execution".to_string(),
            tick_sizes,
            lot_sizes,
            enable_ipc: true,
        }
    }
}

/// Engine state
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EngineState {
    Initializing,
    Running,
    Paused,
    ShuttingDown,
    Stopped,
}

/// Execution engine
pub struct ExecutionEngine {
    config: EngineConfig,
    state: RwLock<EngineState>,
    running: AtomicBool,

    // Components
    matcher_manager: Arc<MatcherManager>,
    order_book_manager: Arc<OrderBookManager>,
    positions: RwLock<HashMap<Symbol, Position>>,

    // Channels
    order_producer: Option<Producer<Order>>,
    fill_consumer: Option<Consumer<Fill>>,

    // IPC
    ipc: RwLock<Option<IpcConnection>>,

    // Stats
    stats: RwLock<EngineStats>,
}

/// Engine statistics
#[derive(Debug, Default)]
pub struct EngineStats {
    pub orders_received: u64,
    pub orders_executed: u64,
    pub orders_cancelled: u64,
    pub fills_generated: u64,
    pub total_volume: f64,
    pub total_value: f64,
    pub last_update_ns: u64,
}

impl ExecutionEngine {
    /// Create a new execution engine
    pub fn new(config: EngineConfig) -> Result<Arc<Self>> {
        info!("Initializing Rust Execution Engine");

        let engine = Arc::new(Self {
            config,
            state: RwLock::new(EngineState::Initializing),
            running: AtomicBool::new(false),
            matcher_manager: Arc::new(MatcherManager::new()),
            order_book_manager: Arc::new(OrderBookManager::new()),
            positions: RwLock::new(HashMap::new()),
            order_producer: None,
            fill_consumer: None,
            ipc: RwLock::new(None),
            stats: RwLock::new(EngineStats::default()),
        });

        Ok(engine)
    }

    /// Start the engine
    pub fn start(self: &Arc<Self>) -> Result<()> {
        let mut state = self.state.write();
        if *state != EngineState::Initializing {
            return Err(ExecutionError::AlreadyRunning);
        }

        info!("Starting Rust Execution Engine");

        // Initialize IPC
        if self.config.enable_ipc {
            match IpcConnection::create(&self.config.ipc_path, self.config.ipc_buffer_size) {
                Ok(ipc) => {
                    *self.ipc.write() = Some(ipc);
                    info!("IPC connection established");
                }
                Err(e) => {
                    warn!("Failed to initialize IPC: {}", e);
                }
            }
        }

        // Initialize ring buffers
        let (order_prod, order_cons) = channel::<Order>(self.config.ring_buffer_capacity)?;
        let (fill_prod, fill_cons) = channel::<Fill>(self.config.ring_buffer_capacity)?;

        // This is a simplified version - in real implementation we'd store these
        // in the struct but Rust's type system makes this complex with Arc<Self>

        *state = EngineState::Running;
        self.running.store(true, Ordering::Release);

        info!("Rust Execution Engine started");
        Ok(())
    }

    /// Stop the engine
    pub fn stop(&self) -> Result<()> {
        info!("Stopping Rust Execution Engine");

        let mut state = self.state.write();
        *state = EngineState::ShuttingDown;
        self.running.store(false, Ordering::Release);

        // Wait for pending operations
        std::thread::sleep(Duration::from_millis(100));

        *state = EngineState::Stopped;
        info!("Rust Execution Engine stopped");

        Ok(())
    }

    /// Check if running
    #[inline]
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::Acquire)
    }

    /// Submit an order
    pub fn submit_order(&self, order: Order) -> Result<Vec<Fill>> {
        if !self.is_running() {
            return Err(ExecutionError::NotInitialized);
        }

        let symbol = order.symbol;
        let tick_size = self.get_tick_size(&symbol);
        let lot_size = self.get_lot_size(&symbol);

        // Get or create matcher
        let matcher = self.matcher_manager.get_or_create(symbol, tick_size, lot_size);

        // Match order
        let fills = matcher.add_order(order)?;

        // Update statistics
        {
            let mut stats = self.stats.write();
            stats.orders_received += 1;
            if !fills.is_empty() {
                stats.orders_executed += 1;
                for fill in &fills {
                    stats.fills_generated += 1;
                    stats.total_volume += fill.quantity;
                    stats.total_value += fill.quantity * fill.price;
                }
            }
        }

        // Update positions
        for fill in &fills {
            self.update_position(fill);
        }

        Ok(fills)
    }

    /// Cancel an order
    pub fn cancel_order(&self, symbol: Symbol, order_id: u64) -> Result<Option<Order>> {
        let tick_size = self.get_tick_size(&symbol);
        let lot_size = self.get_lot_size(&symbol);

        let matcher = self.matcher_manager.get_or_create(symbol, tick_size, lot_size);
        let result = matcher.cancel_order(order_id)?;

        if result.is_some() {
            let mut stats = self.stats.write();
            stats.orders_cancelled += 1;
        }

        Ok(result)
    }

    /// Get order book snapshot
    pub fn get_order_book(&self, symbol: &Symbol, depth: usize) -> Option<OrderBook> {
        let tick_size = self.get_tick_size(symbol);
        let lot_size = self.get_lot_size(symbol);

        self.matcher_manager
            .get_or_create(*symbol, tick_size, lot_size)
            .get_snapshot(depth)
            .into()
    }

    /// Get position for symbol
    pub fn get_position(&self, symbol: &Symbol) -> Option<Position> {
        self.positions.read().get(symbol).copied()
    }

    /// Get all positions
    pub fn get_all_positions(&self) -> Vec<Position> {
        self.positions.read().values().copied().collect()
    }

    /// Get engine statistics
    pub fn get_stats(&self) -> EngineStats {
        self.stats.read().clone()
    }

    /// Get tick size for symbol
    fn get_tick_size(&self, symbol: &Symbol) -> f64 {
        let sym_str = symbol.to_string();
        self.config
            .tick_sizes
            .get(&sym_str)
            .copied()
            .unwrap_or(0.01)
    }

    /// Get lot size for symbol
    fn get_lot_size(&self, symbol: &Symbol) -> f64 {
        let sym_str = symbol.to_string();
        self.config
            .lot_sizes
            .get(&sym_str)
            .copied()
            .unwrap_or(0.0001)
    }

    /// Update position with fill
    fn update_position(&self, fill: &Fill) {
        let mut positions = self.positions.write();
        let position = positions.entry(fill.symbol).or_insert_with(|| Position {
            symbol: fill.symbol,
            ..Default::default()
        });

        position.update_with_fill(fill);
    }

    /// Process IPC messages
    pub fn process_ipc(&self) -> Result<()> {
        let ipc_guard = self.ipc.read();
        if let Some(ipc) = ipc_guard.as_ref() {
            // Receive fills from Go
            let fills = ipc.receive_fills()?;
            for fill in fills {
                self.update_position(&fill);
            }
        }
        Ok(())
    }

    /// Send order via IPC
    pub fn send_order_ipc(&self, order: &Order) -> Result<()> {
        let mut ipc_guard = self.ipc.write();
        if let Some(ref mut ipc) = ipc_guard.as_mut() {
            ipc.send_order(order)?;
        }
        Ok(())
    }
}

impl Clone for EngineStats {
    fn clone(&self) -> Self {
        Self {
            orders_received: self.orders_received,
            orders_executed: self.orders_executed,
            orders_cancelled: self.orders_cancelled,
            fills_generated: self.fills_generated,
            total_volume: self.total_volume,
            total_value: self.total_value,
            last_update_ns: self.last_update_ns,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::{OrderType, Side};

    #[test]
    fn test_engine_basic() {
        let engine = ExecutionEngine::new(EngineConfig::default()).unwrap();
        engine.start().unwrap();

        // Submit a buy order
        let order = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Buy,
            OrderType::Limit,
            50000.0,
            0.1,
        );

        let fills = engine.submit_order(order).unwrap();
        assert!(fills.is_empty()); // No matching sell order

        // Submit matching sell order
        let sell_order = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Sell,
            OrderType::Limit,
            49900.0, // Lower than buy
            0.05,
        );

        let fills = engine.submit_order(sell_order).unwrap();
        assert_eq!(fills.len(), 1);
        assert_eq!(fills[0].quantity, 0.05);

        engine.stop().unwrap();
    }

    #[test]
    fn test_position_tracking() {
        let engine = ExecutionEngine::new(EngineConfig::default()).unwrap();
        engine.start().unwrap();

        let symbol = Symbol::new("BTC", "USDT");

        // Buy 1.0 BTC
        let buy = Order::new(symbol, Side::Buy, OrderType::Limit, 50000.0, 1.0);
        engine.submit_order(buy).unwrap();

        // Sell 0.5 BTC
        let sell = Order::new(symbol, Side::Sell, OrderType::Limit, 49900.0, 0.5);
        engine.submit_order(sell).unwrap();

        // Check position
        let pos = engine.get_position(&symbol);
        assert!(pos.is_some());

        engine.stop().unwrap();
    }
}
