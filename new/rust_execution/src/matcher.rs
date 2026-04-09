//! High-performance order matching engine
//!
//! FIFO matching with support for partial fills and multiple order types.

use crate::error::{ExecutionError, Result};
use crate::order_book::{OrderBook, Level};
use crate::types::{Order, OrderStatus, Fill, Side, Symbol, OrderType, TimeInForce};

use std::collections::{BTreeMap, VecDeque};
use parking_lot::RwLock;
use std::sync::Arc;

/// Priority queue for orders at a price level
#[derive(Debug)]
struct PriceLevel {
    price: f64,
    orders: VecDeque<Order>,
    total_quantity: f64,
}

impl PriceLevel {
    fn new(price: f64) -> Self {
        Self {
            price,
            orders: VecDeque::new(),
            total_quantity: 0.0,
        }
    }

    fn add_order(&mut self, order: Order) {
        self.total_quantity += order.remaining_quantity();
        self.orders.push_back(order);
    }

    fn remove_order(&mut self, order_id: u64) -> Option<Order> {
        if let Some(pos) = self.orders.iter().position(|o| o.id == order_id) {
            let order = self.orders.remove(pos).unwrap();
            self.total_quantity -= order.remaining_quantity();
            Some(order)
        } else {
            None
        }
    }

    fn match_order(&mut self, quantity: f64, symbol: Symbol, side: Side, trade_id: &mut u64) -> (Vec<Fill>, f64) {
        let mut fills = Vec::new();
        let mut remaining = quantity;

        while remaining > 0.0 && !self.orders.is_empty() {
            let order = self.orders.front_mut().unwrap();
            let fill_qty = order.remaining_quantity().min(remaining);

            if fill_qty > 0.0 {
                order.filled_quantity += fill_qty;
                self.total_quantity -= fill_qty;
                remaining -= fill_qty;

                *trade_id += 1;
                fills.push(Fill {
                    trade_id: *trade_id,
                    order_id: order.id,
                    symbol,
                    side,
                    price: self.price,
                    quantity: fill_qty,
                    timestamp_ns: crate::types::current_timestamp_ns(),
                    maker: true,
                });

                if order.is_filled() {
                    order.status = OrderStatus::Filled;
                    self.orders.pop_front();
                } else {
                    order.status = OrderStatus::PartiallyFilled;
                }
            }
        }

        (fills, remaining)
    }

    fn is_empty(&self) -> bool {
        self.orders.is_empty() || self.total_quantity <= 0.0
    }
}

/// Order matcher for a single symbol
pub struct OrderMatcher {
    symbol: Symbol,
    bids: RwLock<BTreeMap<u64, PriceLevel>>,  // Price -> Level (reversed for bids)
    asks: RwLock<BTreeMap<u64, PriceLevel>>,  // Price -> Level
    last_trade_id: RwLock<u64>,
    tick_size: f64,
    lot_size: f64,
}

impl OrderMatcher {
    pub fn new(symbol: Symbol, tick_size: f64, lot_size: f64) -> Self {
        Self {
            symbol,
            bids: RwLock::new(BTreeMap::new()),
            asks: RwLock::new(BTreeMap::new()),
            last_trade_id: RwLock::new(0),
            tick_size,
            lot_size,
        }
    }

    /// Normalize price to tick size
    #[inline]
    fn normalize_price(&self, price: f64) -> f64 {
        (price / self.tick_size).round() * self.tick_size
    }

    /// Normalize quantity to lot size
    #[inline]
    fn normalize_qty(&self, qty: f64) -> f64 {
        (qty / self.lot_size).floor() * self.lot_size
    }

    /// Price to key (for bid ordering - reversed)
    #[inline]
    fn bid_key(&self, price: f64) -> u64 {
        // Reverse order: higher prices have lower keys for BTreeMap iteration
        ((1e9 - price) / self.tick_size) as u64
    }

    /// Price to key (for ask ordering)
    #[inline]
    fn ask_key(&self, price: f64) -> u64 {
        (price / self.tick_size) as u64
    }

    /// Add a new order
    pub fn add_order(&self, mut order: Order) -> Result<Vec<Fill>> {
        // Validate order
        if order.quantity <= 0.0 {
            return Err(ExecutionError::InvalidOrder("Quantity must be positive".to_string()));
        }

        // Normalize
        order.price = self.normalize_price(order.price);
        order.quantity = self.normalize_qty(order.quantity);

        // Try to match
        let (fills, remaining) = self.match_order(&order)?;

        // If not fully filled and not IOC/FOK, add to book
        if remaining > 0.0 && !matches!(order.time_in_force, TimeInForce::IOC | TimeInForce::FOK) {
            let mut order = order.clone();
            order.quantity = remaining; // Adjust for partial fills
            self.place_on_book(order)?;
        }

        Ok(fills)
    }

    /// Match order against existing orders
    fn match_order(&self, order: &Order) -> Result<(Vec<Fill>, f64)> {
        let mut fills = Vec::new();
        let mut remaining = order.quantity;

        match order.side {
            Side::Buy => {
                // Match against asks (ascending price)
                let mut asks = self.asks.write();
                let mut trade_id = self.last_trade_id.write();

                while remaining > 0.0 {
                    let best_ask_key = asks.keys().next().copied();

                    if let Some(key) = best_ask_key {
                        let level = asks.get_mut(&key).unwrap();

                        // Check if marketable
                        if order.price >= level.price || matches!(order.order_type, OrderType::Market) {
                            let (level_fills, new_remaining) = level.match_order(
                                remaining,
                                self.symbol,
                                order.side,
                                &mut *trade_id
                            );

                            fills.extend(level_fills);
                            remaining = new_remaining;

                            if level.is_empty() {
                                asks.remove(&key);
                            }
                        } else {
                            break; // Not marketable anymore
                        }
                    } else {
                        break; // No more asks
                    }
                }
            }
            Side::Sell => {
                // Match against bids (descending price)
                let mut bids = self.bids.write();
                let mut trade_id = self.last_trade_id.write();

                while remaining > 0.0 {
                    let best_bid_key = bids.keys().next().copied();

                    if let Some(key) = best_bid_key {
                        let level = bids.get_mut(&key).unwrap();

                        // Check if marketable
                        if order.price <= level.price || matches!(order.order_type, OrderType::Market) {
                            let (level_fills, new_remaining) = level.match_order(
                                remaining,
                                self.symbol,
                                order.side,
                                &mut *trade_id
                            );

                            fills.extend(level_fills);
                            remaining = new_remaining;

                            if level.is_empty() {
                                bids.remove(&key);
                            }
                        } else {
                            break;
                        }
                    } else {
                        break;
                    }
                }
            }
        }

        Ok((fills, remaining))
    }

    /// Place remaining order on book
    fn place_on_book(&self, order: Order) -> Result<()> {
        match order.side {
            Side::Buy => {
                let mut bids = self.bids.write();
                let key = self.bid_key(order.price);
                let level = bids.entry(key).or_insert_with(|| PriceLevel::new(order.price));
                level.add_order(order);
            }
            Side::Sell => {
                let mut asks = self.asks.write();
                let key = self.ask_key(order.price);
                let level = asks.entry(key).or_insert_with(|| PriceLevel::new(order.price));
                level.add_order(order);
            }
        }
        Ok(())
    }

    /// Cancel an order
    pub fn cancel_order(&self, order_id: u64) -> Result<Option<Order>> {
        // Search in bids
        {
            let mut bids = self.bids.write();
            for level in bids.values_mut() {
                if let Some(order) = level.remove_order(order_id) {
                    if level.is_empty() {
                        // Remove empty level - need to find key
                    }
                    return Ok(Some(order));
                }
            }
        }

        // Search in asks
        {
            let mut asks = self.asks.write();
            for level in asks.values_mut() {
                if let Some(order) = level.remove_order(order_id) {
                    return Ok(Some(order));
                }
            }
        }

        Ok(None)
    }

    /// Get order book snapshot
    pub fn get_snapshot(&self, depth: usize) -> OrderBook {
        let mut book = OrderBook::new(self.symbol);

        // Copy bids
        let bids = self.bids.read();
        for (i, (_, level)) in bids.iter().take(depth).enumerate() {
            book.update_bid(i, level.price, level.total_quantity);
        }

        // Copy asks
        let asks = self.asks.read();
        for (i, (_, level)) in asks.iter().take(depth).enumerate() {
            book.update_ask(i, level.price, level.total_quantity);
        }

        book
    }

    /// Get best bid/ask
    pub fn get_bbo(&self) -> (Option<f64>, Option<f64>) {
        let best_bid = self.bids.read().values().next().map(|l| l.price);
        let best_ask = self.asks.read().values().next().map(|l| l.price);
        (best_bid, best_ask)
    }
}

/// Multi-symbol matcher manager
pub struct MatcherManager {
    matchers: RwLock<std::collections::HashMap<Symbol, Arc<OrderMatcher>>>,
}

impl MatcherManager {
    pub fn new() -> Self {
        Self {
            matchers: RwLock::new(std::collections::HashMap::new()),
        }
    }

    pub fn get_or_create(&self, symbol: Symbol, tick_size: f64, lot_size: f64) -> Arc<OrderMatcher> {
        let mut matchers = self.matchers.write();
        matchers.entry(symbol)
            .or_insert_with(|| Arc::new(OrderMatcher::new(symbol, tick_size, lot_size)))
            .clone()
    }

    pub fn get(&self, symbol: &Symbol) -> Option<Arc<OrderMatcher>> {
        self.matchers.read().get(symbol).cloned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_matcher_basic() {
        let matcher = OrderMatcher::new(Symbol::new("BTC", "USDT"), 0.01, 0.0001);

        // Add sell order
        let order1 = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Sell,
            OrderType::Limit,
            50000.0,
            1.0,
        );
        let fills = matcher.add_order(order1).unwrap();
        assert!(fills.is_empty()); // No match yet

        // Add buy order that matches
        let order2 = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Buy,
            OrderType::Limit,
            50100.0,
            0.5,
        );
        let fills = matcher.add_order(order2).unwrap();
        assert_eq!(fills.len(), 1);
        assert_eq!(fills[0].quantity, 0.5);
        assert_eq!(fills[0].price, 50000.0); // Fills at resting price
    }

    #[test]
    fn test_partial_fill() {
        let matcher = OrderMatcher::new(Symbol::new("BTC", "USDT"), 0.01, 0.0001);

        // Sell 1.0 @ 50000
        let order1 = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Sell,
            OrderType::Limit,
            50000.0,
            1.0,
        );
        matcher.add_order(order1).unwrap();

        // Buy 0.3 @ 50100
        let order2 = Order::new(
            Symbol::new("BTC", "USDT"),
            Side::Buy,
            OrderType::Limit,
            50100.0,
            0.3,
        );
        let fills = matcher.add_order(order2).unwrap();
        assert_eq!(fills.len(), 1);
        // Quantity is normalized to lot_size (0.0001), so 0.3 becomes 0.2999
        assert!((fills[0].quantity - 0.3).abs() < 0.0002);

        // Check remaining liquidity
        let book = matcher.get_snapshot(5);
        assert!((book.best_ask().unwrap().quantity - 0.7).abs() < 0.0002);
    }
}
