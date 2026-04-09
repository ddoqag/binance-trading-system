//! Basic demo of Rust execution engine

use rust_execution::{ExecutionEngine, EngineConfig};
use rust_execution::types::{Order, Side, OrderType, Symbol};

fn main() {
    println!("=== Rust Execution Engine Demo ===\n");

    // Create engine with default config
    let config = EngineConfig::default();
    let engine = ExecutionEngine::new(config).expect("Failed to create engine");

    // Start engine
    engine.start().expect("Failed to start engine");
    println!("Engine started: {}\n", engine.is_running());

    let symbol = Symbol::new("BTC", "USDT");

    // Add some sell orders to the book
    println!("Adding sell orders...");
    for i in 0..5 {
        let price = 50100.0 + (i as f64 * 100.0);
        let order = Order::new(symbol, Side::Sell, OrderType::Limit, price, 0.1);
        engine.submit_order(order).expect("Failed to submit order");
        println!("  Sell {} @ {}", i + 1, price);
    }

    // Add some buy orders
    println!("\nAdding buy orders...");
    for i in 0..5 {
        let price = 50000.0 - (i as f64 * 100.0);
        let order = Order::new(symbol, Side::Buy, OrderType::Limit, price, 0.1);
        engine.submit_order(order).expect("Failed to submit order");
        println!("  Buy {} @ {}", i + 1, price);
    }

    // Get order book snapshot
    println!("\nOrder Book:");
    if let Some(book) = engine.get_order_book(&symbol, 10) {
        println!("{}", book.format(5));

        println!("Best Bid: {:?}", book.best_bid());
        println!("Best Ask: {:?}", book.best_ask());
        println!("Mid Price: {:?}", book.mid_price());
        println!("Spread: {:?}", book.spread());
        println!("Spread %: {:?}", book.spread_pct());
    }

    // Submit a marketable buy order
    println!("\nSubmitting marketable buy order...");
    let marketable_buy = Order::new(symbol, Side::Buy, OrderType::Limit, 50150.0, 0.15);
    let fills = engine.submit_order(marketable_buy).expect("Failed to submit");

    println!("Fills: {}", fills.len());
    for fill in &fills {
        println!("  Fill: {} @ {} (qty: {})", fill.trade_id, fill.price, fill.quantity);
    }

    // Get updated order book
    println!("\nUpdated Order Book:");
    if let Some(book) = engine.get_order_book(&symbol, 10) {
        println!("{}", book.format(5));
    }

    // Get statistics
    let stats = engine.get_stats();
    println!("\nEngine Statistics:");
    println!("  Orders received: {}", stats.orders_received);
    println!("  Orders executed: {}", stats.orders_executed);
    println!("  Fills generated: {}", stats.fills_generated);
    println!("  Total volume: {:.4}", stats.total_volume);

    // Stop engine
    engine.stop().expect("Failed to stop engine");
    println!("\nEngine stopped");
}
