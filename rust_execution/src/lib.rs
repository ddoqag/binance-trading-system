use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::sync::Arc;
use std::sync::Once;
use tokio::runtime::Runtime;

mod engine;
mod types;

use engine::ExecutionEngine;
use types::{Order, OrderSide, OrderType, ExecutionConfig};

static INIT_LOGGER: Once = Once::new();

/// Rust执行引擎Python模块
#[pymodule]
fn binance_execution(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustExecutionEngine>()?;
    m.add_class::<PyOrder>()?;
    m.add_class::<PyExecutionResult>()?;
    Ok(())
}

/// Python可用的订单结构
#[pyclass(from_py_object)]
#[derive(Clone)]
pub struct PyOrder {
    #[pyo3(get, set)]
    pub symbol: String,
    #[pyo3(get, set)]
    pub side: String, // "BUY" or "SELL"
    #[pyo3(get, set)]
    pub order_type: String, // "MARKET", "LIMIT", "IOC", "FOK"
    #[pyo3(get, set)]
    pub quantity: f64,
    #[pyo3(get, set)]
    pub price: Option<f64>,
    #[pyo3(get, set)]
    pub order_id: String,
}

#[pymethods]
impl PyOrder {
    #[new]
    fn new(
        symbol: String,
        side: String,
        order_type: String,
        quantity: f64,
        price: Option<f64>,
    ) -> Self {
        let order_id = uuid::Uuid::new_v4().to_string();
        Self {
            symbol,
            side,
            order_type,
            quantity,
            price,
            order_id,
        }
    }
}

/// 执行结果
#[pyclass]
pub struct PyExecutionResult {
    #[pyo3(get)]
    pub success: bool,
    #[pyo3(get)]
    pub order_id: String,
    #[pyo3(get)]
    pub executed_price: f64,
    #[pyo3(get)]
    pub executed_quantity: f64,
    #[pyo3(get)]
    pub commission: f64,
    #[pyo3(get)]
    pub latency_us: i64, // 微秒级延迟
    #[pyo3(get)]
    pub error_message: Option<String>,
}

/// Rust执行引擎包装器
#[pyclass]
pub struct RustExecutionEngine {
    engine: Arc<ExecutionEngine>,
    runtime: Arc<Runtime>,
}

#[pymethods]
impl RustExecutionEngine {
    #[new]
    #[pyo3(signature = (config=None))]
    fn new(config: Option<Bound<'_, PyDict>>) -> PyResult<Self> {
        INIT_LOGGER.call_once(|| {
            let _ = env_logger::try_init();
        });

        let mut execution_config = ExecutionConfig::default();

        if let Some(cfg) = config {
            if let Ok(Some(threads)) = cfg.get_item("worker_threads") {
                execution_config.worker_threads = threads.extract()?;
            }
            if let Ok(Some(queue_size)) = cfg.get_item("queue_size") {
                execution_config.queue_size = queue_size.extract()?;
            }
            if let Ok(Some(slippage_model)) = cfg.get_item("slippage_model") {
                execution_config.slippage_model = slippage_model.extract()?;
            }
        }

        let runtime = Arc::new(
            tokio::runtime::Builder::new_multi_thread()
                .worker_threads(execution_config.worker_threads)
                .enable_all()
                .build()
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?
        );

        let engine = Arc::new(ExecutionEngine::new(execution_config));

        Ok(Self { engine, runtime })
    }

    /// 提交订单（异步执行）
    fn submit_order(&self, order: &PyOrder) -> PyResult<PyExecutionResult> {
        let start = std::time::Instant::now();

        let order_internal = Order {
            order_id: order.order_id.clone(),
            symbol: order.symbol.clone(),
            side: match order.side.as_str() {
                "BUY" => OrderSide::Buy,
                "SELL" => OrderSide::Sell,
                _ => return Err(pyo3::exceptions::PyValueError::new_err("Invalid side")),
            },
            order_type: match order.order_type.as_str() {
                "MARKET" => OrderType::Market,
                "LIMIT" => OrderType::Limit,
                "IOC" => OrderType::ImmediateOrCancel,
                "FOK" => OrderType::FillOrKill,
                _ => return Err(pyo3::exceptions::PyValueError::new_err("Invalid order type")),
            },
            quantity: order.quantity,
            price: order.price,
            timestamp: chrono::Utc::now(),
        };

        // 模拟执行（实际应连接到交易所）
        let result = self.engine.execute_order(order_internal);
        let latency = start.elapsed().as_micros() as i64;

        match result {
            Ok(exec_result) => Ok(PyExecutionResult {
                success: true,
                order_id: exec_result.order_id,
                executed_price: exec_result.executed_price,
                executed_quantity: exec_result.executed_quantity,
                commission: exec_result.commission,
                latency_us: latency,
                error_message: None,
            }),
            Err(e) => Ok(PyExecutionResult {
                success: false,
                order_id: order.order_id.clone(),
                executed_price: 0.0,
                executed_quantity: 0.0,
                commission: 0.0,
                latency_us: latency,
                error_message: Some(e.to_string()),
            }),
        }
    }

    /// 批量提交订单
    fn submit_orders_batch(&self, orders: Vec<PyOrder>) -> PyResult<Vec<PyExecutionResult>> {
        orders.iter().map(|order| self.submit_order(order)).collect()
    }

    /// 获取引擎统计信息
    fn get_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let stats = self.engine.get_stats();
        let dict = PyDict::new(py);
        dict.set_item("total_orders", stats.total_orders)?;
        dict.set_item("executed_orders", stats.executed_orders)?;
        dict.set_item("avg_latency_us", stats.avg_latency_us)?;
        dict.set_item("errors", stats.errors)?;
        Ok(dict)
    }

    /// 重置统计
    fn reset_stats(&self) {
        self.engine.reset_stats();
    }

    /// 获取当前订单簿快照（简化版）
    fn get_orderbook_snapshot<'py>(&self, py: Python<'py>, symbol: &str) -> PyResult<Bound<'py, PyDict>> {
        let snapshot = self.engine.get_orderbook_snapshot(symbol);
        let dict = PyDict::new(py);
        dict.set_item("symbol", symbol)?;
        dict.set_item("best_bid", snapshot.best_bid)?;
        dict.set_item("best_ask", snapshot.best_ask)?;
        dict.set_item("spread", snapshot.spread)?;
        dict.set_item("timestamp", snapshot.timestamp.to_rfc3339())?;
        Ok(dict)
    }

    /// 模拟市场数据（用于测试）
    fn simulate_market_data(&self, symbol: &str, base_price: f64) {
        self.engine.simulate_market_data(symbol, base_price);
    }

    /// 更新订单簿
    fn update_orderbook(&self, symbol: &str, bids: Vec<(f64, f64)>, asks: Vec<(f64, f64)>) -> PyResult<()> {
        let price_levels_bids: Vec<crate::types::PriceLevel> = bids
            .into_iter()
            .map(|(price, qty)| crate::types::PriceLevel {
                price,
                quantity: qty,
                order_count: 1,
            })
            .collect();

        let price_levels_asks: Vec<crate::types::PriceLevel> = asks
            .into_iter()
            .map(|(price, qty)| crate::types::PriceLevel {
                price,
                quantity: qty,
                order_count: 1,
            })
            .collect();

        self.engine.update_orderbook(symbol, price_levels_bids, price_levels_asks);
        Ok(())
    }
}
