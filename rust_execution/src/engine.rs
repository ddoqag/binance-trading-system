use std::sync::atomic::AtomicU64;
use std::sync::Mutex;
use dashmap::DashMap;
use chrono::Utc;

use crate::types::*;

/// 高性能执行引擎
pub struct ExecutionEngine {
    config: ExecutionConfig,
    stats: Mutex<EngineStats>,
    orderbooks: DashMap<String, Orderbook>,
    order_counter: AtomicU64,
}

impl ExecutionEngine {
    pub fn new(config: ExecutionConfig) -> Self {
        Self {
            config,
            stats: Mutex::new(EngineStats::default()),
            orderbooks: DashMap::new(),
            order_counter: AtomicU64::new(0),
        }
    }

    /// 执行订单
    pub fn execute_order(&self, order: Order) -> Result<ExecutionResult, ExecutionError> {
        let start = std::time::Instant::now();

        // 验证订单
        self.validate_order(&order)?;

        // 获取订单簿
        let orderbook = self.orderbooks
            .get(&order.symbol)
            .ok_or_else(|| ExecutionError::InvalidOrder("Symbol not found".to_string()))?;

        // 计算执行价格（简化版，实际应基于订单簿深度）
        let executed_price = match order.order_type {
            OrderType::Market => {
                match order.side {
                    OrderSide::Buy => orderbook.best_ask()
                        .ok_or(ExecutionError::InsufficientLiquidity)?,
                    OrderSide::Sell => orderbook.best_bid()
                        .ok_or(ExecutionError::InsufficientLiquidity)?,
                }
            }
            OrderType::Limit => {
                order.price.ok_or(ExecutionError::InvalidOrder("Limit order requires price".to_string()))?
            }
            OrderType::ImmediateOrCancel | OrderType::FillOrKill => {
                // 简化处理
                orderbook.mid_price()
                    .ok_or(ExecutionError::InsufficientLiquidity)?
            }
        };

        // 模拟滑点
        let slippage = self.calculate_slippage(&order);
        let final_price = match order.side {
            OrderSide::Buy => executed_price * (1.0 + slippage),
            OrderSide::Sell => executed_price * (1.0 - slippage),
        };

        // 计算手续费
        let commission = order.quantity * final_price * self.config.commission_rate;

        // 更新统计
        {
            let mut stats = self.stats.lock().unwrap();
            stats.total_orders += 1;
            stats.executed_orders += 1;
            stats.total_volume += order.quantity;

            let latency = start.elapsed().as_micros() as f64;
            stats.avg_latency_us = (stats.avg_latency_us * (stats.executed_orders - 1) as f64 + latency)
                / stats.executed_orders as f64;
        }

        Ok(ExecutionResult {
            order_id: order.order_id,
            executed_price: final_price,
            executed_quantity: order.quantity,
            commission,
            timestamp: Utc::now(),
        })
    }

    /// 验证订单
    fn validate_order(&self, order: &Order) -> Result<(), ExecutionError> {
        if order.quantity <= 0.0 {
            return Err(ExecutionError::InvalidOrder("Quantity must be positive".to_string()));
        }

        if order.symbol.is_empty() {
            return Err(ExecutionError::InvalidOrder("Symbol cannot be empty".to_string()));
        }

        match order.order_type {
            OrderType::Limit | OrderType::FillOrKill | OrderType::ImmediateOrCancel => {
                if order.price.is_none() || order.price.unwrap() <= 0.0 {
                    return Err(ExecutionError::InvalidOrder("Price required for limit orders".to_string()));
                }
            }
            _ => {}
        }

        Ok(())
    }

    /// 计算滑点
    fn calculate_slippage(&self, order: &Order) -> f64 {
        // 简化版滑点模型
        // 实际应基于订单簿深度、订单大小等
        match self.config.slippage_model.as_str() {
            "fixed" => 0.0001, // 1 basis point
            "proportional" => {
                // 订单越大，滑点越大
                let base = 0.0001;
                let size_factor = (order.quantity / 1000.0).min(0.01);
                base + size_factor
            }
            _ => 0.0001,
        }
    }

    /// 更新订单簿
    pub fn update_orderbook(&self, symbol: &str, bids: Vec<PriceLevel>, asks: Vec<PriceLevel>) {
        let orderbook = Orderbook {
            symbol: symbol.to_string(),
            bids,
            asks,
            last_update: Utc::now(),
        };

        self.orderbooks.insert(symbol.to_string(), orderbook);
    }

    /// 获取订单簿快照
    pub fn get_orderbook_snapshot(&self, symbol: &str) -> OrderbookSnapshot {
        let default = Orderbook::new(symbol.to_string());

        let orderbook = self.orderbooks
            .get(symbol)
            .map(|o| o.clone())
            .unwrap_or(default);

        OrderbookSnapshot {
            symbol: symbol.to_string(),
            best_bid: orderbook.best_bid().unwrap_or(0.0),
            best_ask: orderbook.best_ask().unwrap_or(0.0),
            spread: orderbook.spread().unwrap_or(0.0),
            timestamp: Utc::now(),
        }
    }

    /// 获取统计信息
    pub fn get_stats(&self) -> EngineStats {
        self.stats.lock().unwrap().clone()
    }

    /// 重置统计
    pub fn reset_stats(&self) {
        *self.stats.lock().unwrap() = EngineStats::default();
    }

    /// 获取活跃交易对列表
    pub fn get_active_symbols(&self) -> Vec<String> {
        self.orderbooks.iter().map(|e| e.key().clone()).collect()
    }

    /// 模拟市场数据更新（用于测试）
    pub fn simulate_market_data(&self, symbol: &str, base_price: f64) {
        // 生成模拟订单簿
        let spread = base_price * 0.0002; // 2 basis points spread

        let bids: Vec<PriceLevel> = (0..10)
            .map(|i| {
                let price = base_price - spread / 2.0 - (i as f64 * base_price * 0.0001);
                let quantity = 10.0 + (i as f64 * 5.0);
                PriceLevel {
                    price,
                    quantity,
                    order_count: (10 - i) as u32,
                }
            })
            .collect();

        let asks: Vec<PriceLevel> = (0..10)
            .map(|i| {
                let price = base_price + spread / 2.0 + (i as f64 * base_price * 0.0001);
                let quantity = 10.0 + (i as f64 * 5.0);
                PriceLevel {
                    price,
                    quantity,
                    order_count: (10 - i) as u32,
                }
            })
            .collect();

        self.update_orderbook(symbol, bids, asks);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_order() -> Order {
        Order {
            order_id: "test-1".to_string(),
            symbol: "BTCUSDT".to_string(),
            side: OrderSide::Buy,
            order_type: OrderType::Market,
            quantity: 0.1,
            price: None,
            timestamp: Utc::now(),
        }
    }

    #[test]
    fn test_order_validation() {
        let engine = ExecutionEngine::new(ExecutionConfig::default());
        let order = create_test_order();

        assert!(engine.validate_order(&order).is_ok());
    }

    #[test]
    fn test_invalid_quantity() {
        let engine = ExecutionEngine::new(ExecutionConfig::default());
        let mut order = create_test_order();
        order.quantity = -1.0;

        assert!(engine.validate_order(&order).is_err());
    }

    #[test]
    fn test_market_data_simulation() {
        let engine = ExecutionEngine::new(ExecutionConfig::default());
        engine.simulate_market_data("BTCUSDT", 50000.0);

        let snapshot = engine.get_orderbook_snapshot("BTCUSDT");
        assert!(snapshot.best_bid > 0.0);
        assert!(snapshot.best_ask > 0.0);
        assert!(snapshot.spread > 0.0);
    }
}
