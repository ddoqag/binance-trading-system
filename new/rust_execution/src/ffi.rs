//! Foreign Function Interface for Python integration
//!
//! Exposes Rust execution engine to Python via PyO3.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use pyo3::wrap_pyfunction;

use std::sync::Arc;

use crate::engine::{ExecutionEngine, EngineConfig, EngineStats};
use crate::types::{Order, Fill, Symbol, Side, OrderType, TimeInForce, OrderStatus};
use crate::order_book::OrderBook;

/// Python wrapper for ExecutionEngine
#[pyclass(name = "ExecutionEngine")]
pub struct PyExecutionEngine {
    inner: Arc<ExecutionEngine>,
}

#[pymethods]
impl PyExecutionEngine {
    #[new]
    fn new(config: Option<&PyDict>) -> PyResult<Self> {
        let mut engine_config = EngineConfig::default();

        if let Some(config) = config {
            if let Ok(Some(capacity)) = config.get_item("ring_buffer_capacity") {
                engine_config.ring_buffer_capacity = capacity.extract()?;
            }
            if let Ok(Some(ipc_size)) = config.get_item("ipc_buffer_size") {
                engine_config.ipc_buffer_size = ipc_size.extract()?;
            }
            if let Ok(Some(ipc_path)) = config.get_item("ipc_path") {
                engine_config.ipc_path = ipc_path.extract()?;
            }
            if let Ok(Some(enable_ipc)) = config.get_item("enable_ipc") {
                engine_config.enable_ipc = enable_ipc.extract()?;
            }
        }

        let inner = ExecutionEngine::new(engine_config)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Ok(Self { inner })
    }

    fn start(&self) -> PyResult<()> {
        self.inner.start()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    fn stop(&self) -> PyResult<()> {
        self.inner.stop()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    }

    #[getter]
    fn is_running(&self) -> bool {
        self.inner.is_running()
    }

    fn submit_order(&self, py: Python, order_dict: &PyDict) -> PyResult<PyObject> {
        let order = dict_to_order(order_dict)?;

        let fills = self.inner.submit_order(order)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        let list = PyList::empty(py);
        for fill in fills {
            list.append(fill_to_dict(py, &fill)?)?;
        }

        Ok(list.into())
    }

    fn cancel_order(&self, symbol_str: &str, order_id: u64) -> PyResult<Option<PyObject>> {
        let symbol = parse_symbol(symbol_str)?;

        match self.inner.cancel_order(symbol, order_id) {
            Ok(Some(order)) => {
                Python::with_gil(|py| {
                    Ok(Some(order_to_dict(py, &order)?))
                })
            }
            Ok(None) => Ok(None),
            Err(e) => Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
        }
    }

    fn get_order_book(&self, py: Python, symbol_str: &str, depth: usize) -> PyResult<Option<PyObject>> {
        let symbol = parse_symbol(symbol_str)?;

        match self.inner.get_order_book(&symbol, depth) {
            Some(book) => Ok(Some(order_book_to_dict(py, &book)?)),
            None => Ok(None),
        }
    }

    fn get_position(&self, py: Python, symbol_str: &str) -> PyResult<Option<PyObject>> {
        let symbol = parse_symbol(symbol_str)?;

        match self.inner.get_position(&symbol) {
            Some(pos) => Ok(Some(position_to_dict(py, &pos)?)),
            None => Ok(None),
        }
    }

    fn get_all_positions(&self, py: Python) -> PyResult<PyObject> {
        let positions = self.inner.get_all_positions();
        let list = PyList::empty(py);

        for pos in positions {
            list.append(position_to_dict(py, &pos)?)?;
        }

        Ok(list.into())
    }

    fn get_stats(&self, py: Python) -> PyResult<PyObject> {
        let stats = self.inner.get_stats();
        stats_to_dict(py, &stats)
    }

    fn __repr__(&self) -> String {
        format!("ExecutionEngine(running={})", self.is_running())
    }
}

/// Initialize the module
#[pymodule]
fn rust_execution(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyExecutionEngine>()?;

    // Add utility functions
    m.add_function(wrap_pyfunction!(generate_order_id, m)?)?;
    m.add_function(wrap_pyfunction!(current_timestamp_ns, m)?)?;

    Ok(())
}

/// Generate unique order ID
#[pyfunction]
fn generate_order_id() -> u64 {
    crate::generate_order_id()
}

/// Get current timestamp in nanoseconds
#[pyfunction]
fn current_timestamp_ns() -> u64 {
    crate::types::current_timestamp_ns()
}

/// Parse symbol string (e.g., "BTCUSDT")
fn parse_symbol(s: &str) -> PyResult<Symbol> {
    if s.len() < 6 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "Invalid symbol format"
        ));
    }

    // Simple heuristic: last 4 chars are quote (USDT), rest is base
    let (base, quote) = if s.ends_with("USDT") {
        (&s[..s.len()-4], "USDT")
    } else if s.ends_with("USD") {
        (&s[..s.len()-3], "USD")
    } else if s.ends_with("BTC") {
        (&s[..s.len()-3], "BTC")
    } else if s.ends_with("ETH") {
        (&s[..s.len()-3], "ETH")
    } else {
        // Default: split in half
        let mid = s.len() / 2;
        (&s[..mid], &s[mid..])
    };

    Ok(Symbol::new(base, quote))
}

/// Convert Python dict to Order
fn dict_to_order(dict: &PyDict) -> PyResult<Order> {
    let symbol_str: String = match dict.get_item("symbol") {
        Ok(Some(v)) => v.extract()?,
        _ => return Err(pyo3::exceptions::PyValueError::new_err("Missing symbol")),
    };
    let symbol = parse_symbol(&symbol_str)?;

    let side_str: String = match dict.get_item("side") {
        Ok(Some(v)) => v.extract()?,
        _ => return Err(pyo3::exceptions::PyValueError::new_err("Missing side")),
    };
    let side = match side_str.to_uppercase().as_str() {
        "BUY" => Side::Buy,
        "SELL" => Side::Sell,
        _ => return Err(pyo3::exceptions::PyValueError::new_err("Invalid side")),
    };

    let order_type_str: String = match dict.get_item("order_type") {
        Ok(Some(v)) => v.extract()?,
        _ => "LIMIT".to_string(),
    };
    let order_type = match order_type_str.to_uppercase().as_str() {
        "MARKET" => OrderType::Market,
        "LIMIT" => OrderType::Limit,
        "STOP_LOSS" => OrderType::StopLoss,
        "TAKE_PROFIT" => OrderType::TakeProfit,
        _ => OrderType::Limit,
    };

    let price: f64 = match dict.get_item("price") {
        Ok(Some(v)) => v.extract().unwrap_or(0.0),
        _ => 0.0,
    };

    let quantity: f64 = match dict.get_item("quantity") {
        Ok(Some(v)) => v.extract()?,
        _ => return Err(pyo3::exceptions::PyValueError::new_err("Missing quantity")),
    };

    let mut order = Order::new(symbol, side, order_type, price, quantity);

    if let Ok(Some(id)) = dict.get_item("id") {
        order.id = id.extract()?;
    }

    if let Ok(Some(tif)) = dict.get_item("time_in_force") {
        let tif_str: String = tif.extract()?;
        order.time_in_force = match tif_str.to_uppercase().as_str() {
            "GTC" => TimeInForce::GTC,
            "IOC" => TimeInForce::IOC,
            "FOK" => TimeInForce::FOK,
            _ => TimeInForce::GTC,
        };
    }

    Ok(order)
}

/// Convert Order to Python dict
fn order_to_dict(py: Python, order: &Order) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("id", order.id)?;
    dict.set_item("symbol", order.symbol.to_string())?;
    dict.set_item("side", match order.side {
        Side::Buy => "BUY",
        Side::Sell => "SELL",
    })?;
    dict.set_item("order_type", match order.order_type {
        OrderType::Market => "MARKET",
        OrderType::Limit => "LIMIT",
        OrderType::StopLoss => "STOP_LOSS",
        OrderType::TakeProfit => "TAKE_PROFIT",
        _ => "UNKNOWN",
    })?;
    dict.set_item("price", order.price)?;
    dict.set_item("quantity", order.quantity)?;
    dict.set_item("filled_quantity", order.filled_quantity)?;
    dict.set_item("remaining_quantity", order.remaining_quantity())?;
    dict.set_item("status", match order.status {
        OrderStatus::New => "NEW",
        OrderStatus::PartiallyFilled => "PARTIALLY_FILLED",
        OrderStatus::Filled => "FILLED",
        OrderStatus::Cancelled => "CANCELLED",
        OrderStatus::Rejected => "REJECTED",
        OrderStatus::Expired => "EXPIRED",
    })?;
    dict.set_item("timestamp_ns", order.timestamp_ns)?;
    Ok(dict.into())
}

/// Convert Fill to Python dict
fn fill_to_dict(py: Python, fill: &Fill) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("trade_id", fill.trade_id)?;
    dict.set_item("order_id", fill.order_id)?;
    dict.set_item("symbol", fill.symbol.to_string())?;
    dict.set_item("side", match fill.side {
        Side::Buy => "BUY",
        Side::Sell => "SELL",
    })?;
    dict.set_item("price", fill.price)?;
    dict.set_item("quantity", fill.quantity)?;
    dict.set_item("timestamp_ns", fill.timestamp_ns)?;
    dict.set_item("maker", fill.maker)?;
    Ok(dict.into())
}

/// Convert OrderBook to Python dict
fn order_book_to_dict(py: Python, book: &OrderBook) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("symbol", book.symbol.to_string())?;

    let bids = PyList::empty(py);
    for level in book.bids.iter().filter(|l| !l.is_empty()) {
        let level_dict = PyDict::new(py);
        level_dict.set_item("price", level.price)?;
        level_dict.set_item("quantity", level.quantity)?;
        level_dict.set_item("order_count", level.order_count)?;
        bids.append(level_dict)?;
    }
    dict.set_item("bids", bids)?;

    let asks = PyList::empty(py);
    for level in book.asks.iter().filter(|l| !l.is_empty()) {
        let level_dict = PyDict::new(py);
        level_dict.set_item("price", level.price)?;
        level_dict.set_item("quantity", level.quantity)?;
        level_dict.set_item("order_count", level.order_count)?;
        asks.append(level_dict)?;
    }
    dict.set_item("asks", asks)?;

    dict.set_item("last_update_ns", book.last_update_ns)?;
    dict.set_item("last_price", book.last_price)?;
    dict.set_item("last_quantity", book.last_quantity)?;

    Ok(dict.into())
}

/// Convert Position to Python dict
fn position_to_dict(py: Python, pos: &crate::types::Position) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("symbol", pos.symbol.to_string())?;
    dict.set_item("quantity", pos.quantity)?;
    dict.set_item("avg_price", pos.avg_price)?;
    dict.set_item("unrealized_pnl", pos.unrealized_pnl)?;
    dict.set_item("realized_pnl", pos.realized_pnl)?;
    Ok(dict.into())
}

/// Convert EngineStats to Python dict
fn stats_to_dict(py: Python, stats: &EngineStats) -> PyResult<PyObject> {
    let dict = PyDict::new(py);
    dict.set_item("orders_received", stats.orders_received)?;
    dict.set_item("orders_executed", stats.orders_executed)?;
    dict.set_item("orders_cancelled", stats.orders_cancelled)?;
    dict.set_item("fills_generated", stats.fills_generated)?;
    dict.set_item("total_volume", stats.total_volume)?;
    dict.set_item("total_value", stats.total_value)?;
    dict.set_item("last_update_ns", stats.last_update_ns)?;
    Ok(dict.into())
}
