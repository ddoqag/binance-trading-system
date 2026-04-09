//! Core types for the execution engine

use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

/// Order side
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    #[inline]
    pub fn opposite(&self) -> Self {
        match self {
            Side::Buy => Side::Sell,
            Side::Sell => Side::Buy,
        }
    }

    #[inline]
    pub fn sign(&self) -> i8 {
        match self {
            Side::Buy => 1,
            Side::Sell => -1,
        }
    }
}

/// Order type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    StopLoss,
    TakeProfit,
    StopLossLimit,
    TakeProfitLimit,
}

/// Time in force
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TimeInForce {
    GTC, // Good Till Cancelled
    IOC, // Immediate or Cancel
    FOK, // Fill or Kill
}

impl Default for TimeInForce {
    fn default() -> Self {
        TimeInForce::GTC
    }
}

/// Order status
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderStatus {
    New,
    PartiallyFilled,
    Filled,
    Cancelled,
    Rejected,
    Expired,
}

/// Order struct - optimized for cache efficiency
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub id: u64,
    pub symbol: Symbol,
    pub side: Side,
    pub order_type: OrderType,
    pub price: f64,
    pub quantity: f64,
    pub filled_quantity: f64,
    pub time_in_force: TimeInForce,
    pub status: OrderStatus,
    pub timestamp_ns: u64,
    pub client_order_id: Option<String>,
}

impl Order {
    pub fn new(
        symbol: Symbol,
        side: Side,
        order_type: OrderType,
        price: f64,
        quantity: f64,
    ) -> Self {
        Self {
            id: super::generate_order_id(),
            symbol,
            side,
            order_type,
            price,
            quantity,
            filled_quantity: 0.0,
            time_in_force: TimeInForce::default(),
            status: OrderStatus::New,
            timestamp_ns: current_timestamp_ns(),
            client_order_id: None,
        }
    }

    #[inline]
    pub fn remaining_quantity(&self) -> f64 {
        self.quantity - self.filled_quantity
    }

    #[inline]
    pub fn is_filled(&self) -> bool {
        self.remaining_quantity() <= 0.0
    }

    #[inline]
    pub fn is_active(&self) -> bool {
        matches!(self.status, OrderStatus::New | OrderStatus::PartiallyFilled)
    }
}

/// Symbol - compact representation
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
pub struct Symbol {
    pub base: [u8; 8],
    pub quote: [u8; 8],
}

impl Symbol {
    pub fn new(base: &str, quote: &str) -> Self {
        let mut s = Self {
            base: [0u8; 8],
            quote: [0u8; 8],
        };
        s.base[..base.len().min(8)].copy_from_slice(&base.as_bytes()[..base.len().min(8)]);
        s.quote[..quote.len().min(8)].copy_from_slice(&quote.as_bytes()[..quote.len().min(8)]);
        s
    }

    pub fn to_string(&self) -> String {
        let base = String::from_utf8_lossy(&self.base).trim_end_matches('\0').to_string();
        let quote = String::from_utf8_lossy(&self.quote).trim_end_matches('\0').to_string();
        format!("{}{}", base, quote)
    }
}

/// Trade/Fill record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Fill {
    pub trade_id: u64,
    pub order_id: u64,
    pub symbol: Symbol,
    pub side: Side,
    pub price: f64,
    pub quantity: f64,
    pub timestamp_ns: u64,
    pub maker: bool, // true if maker, false if taker
}

/// Market tick
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct Tick {
    pub symbol: Symbol,
    pub bid: f64,
    pub ask: f64,
    pub bid_qty: f64,
    pub ask_qty: f64,
    pub last_price: f64,
    pub last_qty: f64,
    pub timestamp_ns: u64,
}

/// Position
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct Position {
    pub symbol: Symbol,
    pub quantity: f64,
    pub avg_price: f64,
    pub unrealized_pnl: f64,
    pub realized_pnl: f64,
}

impl Position {
    #[inline]
    pub fn market_value(&self, price: f64) -> f64 {
        self.quantity * price
    }

    pub fn update_with_fill(&mut self, fill: &Fill) {
        let qty = if matches!(fill.side, Side::Buy) {
            fill.quantity
        } else {
            -fill.quantity
        };

        if self.quantity * qty > 0.0 {
            // Adding to position
            let total_qty = self.quantity + qty;
            self.avg_price = (self.quantity * self.avg_price + qty * fill.price) / total_qty;
            self.quantity = total_qty;
        } else {
            // Reducing or flipping position
            if self.quantity.abs() >= fill.quantity {
                // Reducing
                let realized = if self.quantity > 0.0 {
                    (fill.price - self.avg_price) * fill.quantity
                } else {
                    (self.avg_price - fill.price) * fill.quantity
                };
                self.realized_pnl += realized;
                self.quantity += qty;
            } else {
                // Flipping
                let realized = if self.quantity > 0.0 {
                    (fill.price - self.avg_price) * self.quantity.abs()
                } else {
                    (self.avg_price - fill.price) * self.quantity.abs()
                };
                self.realized_pnl += realized;
                self.avg_price = fill.price;
                self.quantity = qty;
            }
        }

        if self.quantity == 0.0 {
            self.avg_price = 0.0;
        }
    }
}

/// Get current timestamp in nanoseconds
#[inline]
pub fn current_timestamp_ns() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos() as u64
}

/// Get current timestamp in microseconds
#[inline]
pub fn current_timestamp_us() -> u64 {
    (current_timestamp_ns() / 1000) as u64
}

/// Get current timestamp in milliseconds
#[inline]
pub fn current_timestamp_ms() -> u64 {
    (current_timestamp_ns() / 1_000_000) as u64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_symbol_creation() {
        let sym = Symbol::new("BTC", "USDT");
        assert_eq!(sym.to_string(), "BTCUSDT");
    }

    #[test]
    fn test_order_remaining() {
        let mut order = Order::new(Symbol::new("BTC", "USDT"), Side::Buy, OrderType::Limit, 50000.0, 1.0);
        order.filled_quantity = 0.3;
        assert_eq!(order.remaining_quantity(), 0.7);
    }

    #[test]
    fn test_position_update() {
        let mut pos = Position::default();
        pos.symbol = Symbol::new("BTC", "USDT");

        let fill = Fill {
            trade_id: 1,
            order_id: 1,
            symbol: Symbol::new("BTC", "USDT"),
            side: Side::Buy,
            price: 50000.0,
            quantity: 1.0,
            timestamp_ns: current_timestamp_ns(),
            maker: true,
        };

        pos.update_with_fill(&fill);
        assert_eq!(pos.quantity, 1.0);
        assert_eq!(pos.avg_price, 50000.0);
    }
}
