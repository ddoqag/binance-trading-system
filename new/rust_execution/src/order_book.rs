//! Zero-copy Order Book implementation
//!
//! Fixed-size order book with 50 levels per side.
//! Uses stack-allocated arrays for cache efficiency.

use crate::types::{Side, Symbol, Tick, Order, OrderType};
use crate::error::Result;

/// Number of price levels
pub const LEVELS: usize = 50;

/// Price level
#[derive(Debug, Clone, Copy, Default)]
pub struct Level {
    pub price: f64,
    pub quantity: f64,
    pub order_count: u32,
}

impl Level {
    #[inline]
    pub fn is_empty(&self) -> bool {
        self.quantity <= 0.0 || self.price <= 0.0
    }

    #[inline]
    pub fn value(&self) -> f64 {
        self.price * self.quantity
    }
}

/// Zero-copy order book with fixed size
#[derive(Debug, Clone)]
pub struct OrderBook {
    pub symbol: Symbol,
    pub bids: [Level; LEVELS],
    pub asks: [Level; LEVELS],
    pub last_update_ns: u64,
    pub last_price: f64,
    pub last_quantity: f64,
}

impl OrderBook {
    /// Create new empty order book
    pub fn new(symbol: Symbol) -> Self {
        Self {
            symbol,
            bids: [Level::default(); LEVELS],
            asks: [Level::default(); LEVELS],
            last_update_ns: 0,
            last_price: 0.0,
            last_quantity: 0.0,
        }
    }

    /// Update a bid level
    #[inline]
    pub fn update_bid(&mut self, level: usize, price: f64, quantity: f64) {
        if level < LEVELS {
            self.bids[level] = Level {
                price,
                quantity,
                order_count: 0,
            };
            self.last_update_ns = crate::types::current_timestamp_ns();
        }
    }

    /// Update an ask level
    #[inline]
    pub fn update_ask(&mut self, level: usize, price: f64, quantity: f64) {
        if level < LEVELS {
            self.asks[level] = Level {
                price,
                quantity,
                order_count: 0,
            };
            self.last_update_ns = crate::types::current_timestamp_ns();
        }
    }

    /// Get best bid
    #[inline]
    pub fn best_bid(&self) -> Option<&Level> {
        self.bids.iter().find(|l| !l.is_empty())
    }

    /// Get best ask
    #[inline]
    pub fn best_ask(&self) -> Option<&Level> {
        self.asks.iter().find(|l| !l.is_empty())
    }

    /// Get mid price
    #[inline]
    pub fn mid_price(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(bid), Some(ask)) => Some((bid.price + ask.price) / 2.0),
            _ => None,
        }
    }

    /// Get spread
    #[inline]
    pub fn spread(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(bid), Some(ask)) => Some(ask.price - bid.price),
            _ => None,
        }
    }

    /// Get spread as percentage
    #[inline]
    pub fn spread_pct(&self) -> Option<f64> {
        match (self.spread(), self.mid_price()) {
            (Some(spread), Some(mid)) if mid > 0.0 => Some((spread / mid) * 100.0),
            _ => None,
        }
    }

    /// Calculate bid-ask imbalance
    #[inline]
    pub fn imbalance(&self, depth: usize) -> Option<f64> {
        let depth = depth.min(LEVELS);

        let bid_vol: f64 = self.bids[..depth]
            .iter()
            .filter(|l| !l.is_empty())
            .map(|l| l.quantity)
            .sum();

        let ask_vol: f64 = self.asks[..depth]
            .iter()
            .filter(|l| !l.is_empty())
            .map(|l| l.quantity)
            .sum();

        let total = bid_vol + ask_vol;
        if total > 0.0 {
            Some((bid_vol - ask_vol) / total)
        } else {
            None
        }
    }

    /// Get volume at price level
    #[inline]
    pub fn volume_at_price(&self, price: f64, side: Side) -> f64 {
        let levels = match side {
            Side::Buy => &self.bids,
            Side::Sell => &self.asks,
        };

        levels
            .iter()
            .find(|l| (l.price - price).abs() < f64::EPSILON)
            .map(|l| l.quantity)
            .unwrap_or(0.0)
    }

    /// Calculate average price for a given quantity
    pub fn average_fill_price(&self, quantity: f64, side: Side) -> Option<f64> {
        let levels = match side {
            Side::Buy => &self.asks,  // Buy fills against asks
            Side::Sell => &self.bids, // Sell fills against bids
        };

        let mut remaining = quantity;
        let mut total_value = 0.0;

        for level in levels.iter().filter(|l| !l.is_empty()) {
            let fill_qty = level.quantity.min(remaining);
            total_value += fill_qty * level.price;
            remaining -= fill_qty;

            if remaining <= 0.0 {
                break;
            }
        }

        if remaining <= 0.0 && quantity > 0.0 {
            Some(total_value / quantity)
        } else {
            None // Insufficient liquidity
        }
    }

    /// Check if order would fill immediately (marketable)
    pub fn is_marketable(&self, order: &Order) -> bool {
        match order.side {
            Side::Buy => {
                if let Some(ask) = self.best_ask() {
                    order.price >= ask.price || matches!(order.order_type, OrderType::Market)
                } else {
                    false
                }
            }
            Side::Sell => {
                if let Some(bid) = self.best_bid() {
                    order.price <= bid.price || matches!(order.order_type, OrderType::Market)
                } else {
                    false
                }
            }
        }
    }

    /// Calculate market impact in bps
    pub fn market_impact_bps(&self, quantity: f64, side: Side) -> Option<f64> {
        let avg_price = self.average_fill_price(quantity, side)?;
        let mid = self.mid_price()?;

        if mid > 0.0 {
            Some(((avg_price - mid) / mid).abs() * 10000.0)
        } else {
            None
        }
    }

    /// Get total bid/ask volume
    pub fn total_volume(&self, side: Side, depth: usize) -> f64 {
        let depth = depth.min(LEVELS);
        let levels = match side {
            Side::Buy => &self.bids[..depth],
            Side::Sell => &self.asks[..depth],
        };

        levels
            .iter()
            .filter(|l| !l.is_empty())
            .map(|l| l.quantity)
            .sum()
    }

    /// Update from tick
    pub fn update_from_tick(&mut self, tick: &Tick) {
        self.last_price = tick.last_price;
        self.last_quantity = tick.last_qty;
        self.last_update_ns = tick.timestamp_ns;
    }

    /// Get order book depth as vector
    pub fn get_depth(&self, levels: usize) -> (Vec<Level>, Vec<Level>) {
        let n = levels.min(LEVELS);
        let bids: Vec<_> = self.bids[..n]
            .iter()
            .filter(|l| !l.is_empty())
            .cloned()
            .collect();
        let asks: Vec<_> = self.asks[..n]
            .iter()
            .filter(|l| !l.is_empty())
            .cloned()
            .collect();
        (bids, asks)
    }

    /// Format for display
    pub fn format(&self, depth: usize) -> String {
        let (bids, asks) = self.get_depth(depth);
        let mut output = format!("Order Book: {}\n", self.symbol.to_string());
        output.push_str(&format!("{:<12} {:<12} | {:<12} {:<12}\n", "Bid Qty", "Bid Price", "Ask Price", "Ask Qty"));
        output.push_str(&"-".repeat(55));
        output.push('\n');

        for i in 0..depth.max(bids.len()).max(asks.len()) {
            let bid_str = bids.get(i)
                .map(|l| format!("{:>10.4} {:>10.2}", l.quantity, l.price))
                .unwrap_or_else(|| "           ".repeat(2));

            let ask_str = asks.get(i)
                .map(|l| format!("{:>10.2} {:>10.4}", l.price, l.quantity))
                .unwrap_or_else(|| "           ".repeat(2));

            output.push_str(&format!("{} | {}\n", bid_str, ask_str));
        }

        output
    }
}

/// Order book manager for multiple symbols
pub struct OrderBookManager {
    books: parking_lot::RwLock<std::collections::HashMap<Symbol, OrderBook>>,
}

impl OrderBookManager {
    pub fn new() -> Self {
        Self {
            books: parking_lot::RwLock::new(std::collections::HashMap::new()),
        }
    }

    pub fn get_or_create(&self, symbol: Symbol) -> OrderBook {
        let mut books = self.books.write();
        books.entry(symbol).or_insert_with(|| OrderBook::new(symbol)).clone()
    }

    pub fn update_book<F>(&self, symbol: Symbol, f: F)
    where
        F: FnOnce(&mut OrderBook),
    {
        let mut books = self.books.write();
        let book = books.entry(symbol).or_insert_with(|| OrderBook::new(symbol));
        f(book);
    }

    pub fn get_book(&self, symbol: &Symbol) -> Option<OrderBook> {
        let books = self.books.read();
        books.get(symbol).cloned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_order_book_basic() {
        let mut book = OrderBook::new(Symbol::new("BTC", "USDT"));

        book.update_bid(0, 50000.0, 1.0);
        book.update_ask(0, 50100.0, 0.5);

        assert_eq!(book.best_bid().unwrap().price, 50000.0);
        assert_eq!(book.best_ask().unwrap().price, 50100.0);
        assert_eq!(book.mid_price(), Some(50050.0));
        assert_eq!(book.spread(), Some(100.0));
    }

    #[test]
    fn test_average_fill_price() {
        let mut book = OrderBook::new(Symbol::new("BTC", "USDT"));

        book.update_ask(0, 50000.0, 0.5);
        book.update_ask(1, 50100.0, 0.5);
        book.update_ask(2, 50200.0, 1.0);

        let avg_price = book.average_fill_price(1.0, Side::Buy);
        assert!(avg_price.is_some());
        // 0.5 @ 50000 + 0.5 @ 50100 = 25000 + 25050 = 50050 / 1.0 = 50050
        assert_eq!(avg_price.unwrap(), 50050.0);
    }

    #[test]
    fn test_imbalance() {
        let mut book = OrderBook::new(Symbol::new("BTC", "USDT"));

        book.update_bid(0, 50000.0, 2.0);
        book.update_ask(0, 50100.0, 1.0);

        let imbalance = book.imbalance(1);
        assert!(imbalance.is_some());
        // (2.0 - 1.0) / (2.0 + 1.0) = 1/3 ≈ 0.333
        assert!((imbalance.unwrap() - 0.333).abs() < 0.01);
    }
}
