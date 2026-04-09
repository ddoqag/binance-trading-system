//! Benchmark order throughput

use rust_execution::{ExecutionEngine, EngineConfig};
use rust_execution::types::{Order, Side, OrderType, Symbol};
use std::time::{Duration, Instant};

fn main() {
    println!("=== Rust Execution Engine Throughput Benchmark ===\n");

    let config = EngineConfig::default();
    let engine = ExecutionEngine::new(config).expect("Failed to create engine");
    engine.start().expect("Failed to start engine");

    let symbol = Symbol::new("BTC", "USDT");
    let num_orders = 100_000;

    // Pre-populate book with resting orders
    println!("Pre-populating order book...");
    for i in 0..100 {
        let sell_order = Order::new(symbol, Side::Sell, OrderType::Limit, 51000.0 + (i as f64 * 10.0), 1.0);
        engine.submit_order(sell_order).unwrap();
    }

    // Benchmark order submission
    println!("Benchmarking {} orders...", num_orders);
    let start = Instant::now();

    for i in 0..num_orders {
        // Alternate between buy and sell
        let side = if i % 2 == 0 { Side::Buy } else { Side::Sell };
        let price = if i % 2 == 0 { 50000.0 } else { 51000.0 };
        let order = Order::new(symbol, side, OrderType::Limit, price, 0.01);

        engine.submit_order(order).unwrap();
    }

    let elapsed = start.elapsed();
    let orders_per_sec = num_orders as f64 / elapsed.as_secs_f64();

    println!("\nResults:");
    println!("  Total orders: {}", num_orders);
    println!("  Elapsed time: {:?}", elapsed);
    println!("  Throughput: {:.2} orders/sec", orders_per_sec);
    println!("  Latency: {:.2} μs/order", elapsed.as_micros() as f64 / num_orders as f64);

    let stats = engine.get_stats();
    println!("\nEngine Stats:");
    println!("  Orders received: {}", stats.orders_received);
    println!("  Fills generated: {}", stats.fills_generated);

    engine.stop().expect("Failed to stop engine");
}
