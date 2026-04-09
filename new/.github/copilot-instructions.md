# Project Guidelines

## Code Style

**Go**: Follow `go fmt` and `go vet`. Functions <50 lines preferred, files <800 lines. All errors handled explicitly. Prefer immutable objects over mutation.

**Python**: PEP 8 compliant. Type annotations required. Functions <50 lines preferred. Use `@dataclass` for state management.

**Shared Memory**: 144-byte protocol with sequence lock synchronization. Never modify struct alignment.

## Architecture

**Hybrid Go + Python System**:
- Go engine: Microsecond WebSocket feeds, order execution, risk management
- Python brain: RL decisions, regime detection, strategy orchestration
- Communication: mmap shared memory (144 bytes) with lock-free sequence locks

**Core Philosophy**: Execution Alpha - optimize timing and queue position, not price prediction.

## Build and Test

**Go Engine**:
```bash
cd core_go && go mod tidy
cd core_go && go build -o hft_engine.exe .
cd core_go && go test -v ./...
```

**Python Brain**:
```bash
pip install -r brain_py/requirements.txt
cd brain_py && python -m pytest tests/ -v
```

**System Integration**:
```bash
python test_system.py  # Component verification
python end_to_end_test.py  # Full integration (requires API keys)
```

## Conventions

- **Error Handling**: Explicit everywhere - no silent failures
- **State Machines**: Strict FSM pattern for order lifecycle
- **Configuration**: 3-tier hierarchy (defaults → file/env → runtime)
- **Testing**: Table-driven Go tests, pytest with fixtures for Python
- **Shared Memory**: Sequence lock pattern (seq == seq_end validation)
- **Logging**: Direct `log` package in Go, `logging` module in Python

## Key Files

- `protocol.h` - Shared memory protocol definition (144 bytes exactly)
- `core_go/engine.go` - Main Go execution engine
- `brain_py/agent.py` - SAC RL agent implementation
- `core_go/order_fsm.go` - Order state machine (template for FSMs)
- `core_go/ab_testing.go` - Statistical model comparison framework

See `AGENTS.md` for complete project documentation and `CLAUDE.md` for detailed operational guidance.</content>
<parameter name="filePath">d:\binance\new\.github\copilot-instructions.md