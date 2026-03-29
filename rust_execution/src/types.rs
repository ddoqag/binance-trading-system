use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// 订单方向
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderSide {
    Buy,
    Sell,
}

/// 订单类型
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OrderType {
    Market,
    Limit,
    ImmediateOrCancel, // IOC
    FillOrKill,        // FOK
}

/// 订单结构
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    pub order_id: String,
    pub symbol: String,
    pub side: OrderSide,
    pub order_type: OrderType,
    pub quantity: f64,
    pub price: Option<f64>,
    pub timestamp: DateTime<Utc>,
}

/// 执行结果
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionResult {
    pub order_id: String,
    pub executed_price: f64,
    pub executed_quantity: f64,
    pub commission: f64,
    pub timestamp: DateTime<Utc>,
}

/// 执行配置
#[derive(Debug, Clone)]
pub struct ExecutionConfig {
    pub worker_threads: usize,
    pub queue_size: usize,
    pub slippage_model: String,
    pub commission_rate: f64,
    pub latency_simulation_us: u64, // 模拟延迟（微秒）
}

impl Default for ExecutionConfig {
    fn default() -> Self {
        Self {
            worker_threads: 4,
            queue_size: 10000,
            slippage_model: "fixed".to_string(),
            commission_rate: 0.001,
            latency_simulation_us: 100, // 100微秒
        }
    }
}

/// 引擎统计
#[derive(Debug, Clone, Default)]
pub struct EngineStats {
    pub total_orders: u64,
    pub executed_orders: u64,
    pub rejected_orders: u64,
    pub avg_latency_us: f64,
    pub errors: u64,
    pub total_volume: f64,
}

/// 订单簿快照
#[derive(Debug, Clone)]
pub struct OrderbookSnapshot {
    pub symbol: String,
    pub best_bid: f64,
    pub best_ask: f64,
    pub spread: f64,
    pub timestamp: DateTime<Utc>,
}

/// 执行错误
#[derive(Error, Debug)]
pub enum ExecutionError {
    #[error("Invalid order: {0}")]
    InvalidOrder(String),
    #[error("Insufficient liquidity")]
    InsufficientLiquidity,
    #[error("Price out of range")]
    PriceOutOfRange,
    #[error("Order rejected: {0}")]
    OrderRejected(String),
    #[error("Internal error: {0}")]
    InternalError(String),
}

/// 价格级别
#[derive(Debug, Clone)]
pub struct PriceLevel {
    pub price: f64,
    pub quantity: f64,
    pub order_count: u32,
}

/// 订单簿
#[derive(Debug, Clone)]
pub struct Orderbook {
    pub symbol: String,
    pub bids: Vec<PriceLevel>, // 降序
    pub asks: Vec<PriceLevel>, // 升序
    pub last_update: DateTime<Utc>,
}

impl Orderbook {
    pub fn new(symbol: String) -> Self {
        Self {
            symbol,
            bids: Vec::new(),
            asks: Vec::new(),
            last_update: Utc::now(),
        }
    }

    /// 获取最优买价
    pub fn best_bid(&self) -> Option<f64> {
        self.bids.first().map(|l| l.price)
    }

    /// 获取最优卖价
    pub fn best_ask(&self) -> Option<f64> {
        self.asks.first().map(|l| l.price)
    }

    /// 获取价差
    pub fn spread(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(bid), Some(ask)) => Some(ask - bid),
            _ => None,
        }
    }

    /// 获取中间价
    pub fn mid_price(&self) -> Option<f64> {
        match (self.best_bid(), self.best_ask()) {
            (Some(bid), Some(ask)) => Some((bid + ask) / 2.0),
            _ => None,
        }
    }

    /// 获取订单簿不平衡度 (-1 到 1，正值表示买方压力大)
    pub fn imbalance(&self, depth: usize) -> f64 {
        let bid_volume: f64 = self.bids.iter().take(depth).map(|l| l.quantity).sum();
        let ask_volume: f64 = self.asks.iter().take(depth).map(|l| l.quantity).sum();

        if bid_volume + ask_volume > 0.0 {
            (bid_volume - ask_volume) / (bid_volume + ask_volume)
        } else {
            0.0
        }
    }
}
