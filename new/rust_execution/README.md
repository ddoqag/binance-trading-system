# Rust Execution Engine

High-performance Rust execution engine for HFT trading. Provides zero-copy order book, lock-free ring buffer, and ultra-low latency matching.

## Features

- **Zero-copy Order Book**: Fixed-size arrays for cache efficiency
- **Lock-free Ring Buffer**: SPSC queue for inter-thread communication
- **FIFO Matching**: Standard price-time priority matching
- **Shared Memory IPC**: Zero-copy communication with Go engine
- **Python Bindings**: PyO3 integration for Python ecosystem

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Rust Execution Engine                     │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Order Matcher│  │   IPC        │  │   Ring       │      │
│  │   (FIFO)     │  │  (Shared Mem)│  │   Buffer     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                  │              │
│  ┌──────┴─────────────────┴──────────────────┴───────┐      │
│  │              Execution Engine Core                 │      │
│  └────────────────────────────────────────────────────┘      │
│         │                                                    │
│  ┌──────┴──────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Order Book  │  │   Position   │  │   Stats      │       │
│  │  Manager    │  │   Tracker    │  │              │       │
│  └─────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
       ┌──────────────┐              ┌──────────────┐
       │  Go Engine   │              │   Python     │
       │  (via IPC)   │              │  (via FFI)   │
       └──────────────┘              └──────────────┘
```

## Building

### Prerequisites

- Rust 1.70+
- Python 3.8+ (for Python bindings)

### Build Library

```bash
cd rust_execution
cargo build --release
```

### Build Python Module

```bash
# Install maturin
pip install maturin

# Build Python wheel
maturin build --release

# Install locally
maturin develop
```

### Run Tests

```bash
cargo test
```

### Run Benchmarks

```bash
cargo run --example bench_throughput --release
```

## Usage

### Standalone Binary

```bash
cargo run --release
```

### Rust Library

```rust
use rust_execution::{ExecutionEngine, EngineConfig};
use rust_execution::types::{Order, Side, OrderType, Symbol};

fn main() {
    let engine = ExecutionEngine::new(EngineConfig::default()).unwrap();
    engine.start().unwrap();

    let order = Order::new(
        Symbol::new("BTC", "USDT"),
        Side::Buy,
        OrderType::Limit,
        50000.0,
        1.0,
    );

    let fills = engine.submit_order(order).unwrap();
    println!("Fills: {:?}", fills);

    engine.stop().unwrap();
}
```

### Python

```python
import rust_execution

# Create engine
engine = rust_execution.ExecutionEngine({
    "ring_buffer_capacity": 65536,
    "enable_ipc": True,
})

# Start engine
engine.start()

# Submit order
order = {
    "symbol": "BTCUSDT",
    "side": "BUY",
    "order_type": "LIMIT",
    "price": 50000.0,
    "quantity": 0.1,
}
fills = engine.submit_order(order)
print(f"Fills: {fills}")

# Get order book
book = engine.get_order_book("BTCUSDT", 10)
print(f"Bids: {book['bids']}")
print(f"Asks: {book['asks']}")

# Get stats
stats = engine.get_stats()
print(f"Orders: {stats['orders_received']}")

# Stop engine
engine.stop()
```

## Performance

On a typical development machine:

| Metric | Value |
|--------|-------|
| Order Throughput | 500,000+ orders/sec |
| Matching Latency | < 1 μs |
| Order Book Updates | 2M+ updates/sec |
| Memory Usage | < 100 MB |

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `ring_buffer_capacity` | 65536 | Ring buffer size (power of 2) |
| `ipc_buffer_size` | 16 MB | Shared memory buffer size |
| `ipc_path` | /tmp/rust_execution | IPC file path |
| `tick_size` | 0.01 | Minimum price increment |
| `lot_size` | 0.0001 | Minimum quantity |

## License

MIT
