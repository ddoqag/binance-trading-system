#!/bin/bash
#
# start.sh - HFT Trading System Startup Script
#
# Usage: ./start.sh [symbol] [mode]
#   symbol: trading pair (default: btcusdt)
#   mode: paper|live (default: paper)
#
# This script:
# 1. Sets up CPU affinity for optimal performance
# 2. Starts the Go execution engine
# 3. Starts the Python AI brain
# 4. Monitors process health

set -e

# Configuration
SYMBOL=${1:-"btcusdt"}
MODE=${2:-"paper"}
SHM_PATH="/tmp/hft_trading_shm"

# CPU affinity configuration
# Core 0-3: System/OS
# Core 4-7: Go execution engine (network + execution)
# Core 8-11: Python AI brain
# Core 12-15: Data processing / monitoring
GO_CPUS="4,5,6,7"
PYTHON_CPUS="8,9,10,11"

echo "=============================================="
echo "  HFT Trading System Startup"
echo "=============================================="
echo "Symbol: $SYMBOL"
echo "Mode: $MODE"
echo "Go Engine CPUs: $GO_CPUS"
echo "Python Brain CPUs: $PYTHON_CPUS"
echo "=============================================="

# Clean up previous shared memory
if [ -f "$SHM_PATH" ]; then
    echo "Cleaning up previous shared memory..."
    rm -f "$SHM_PATH"
fi

# Create necessary directories
mkdir -p logs
mkdir -p data
mkdir -p checkpoints

# Check if taskset is available (Linux only)
if command -v taskset &> /dev/null; then
    TASKSET_AVAILABLE=true
else
    TASKSET_AVAILABLE=false
    echo "Warning: taskset not available (macOS/Windows), CPU affinity not set"
fi

# Function to cleanup processes on exit
cleanup() {
    echo ""
    echo "Shutting down HFT System..."
    if [ -n "$GO_PID" ]; then
        kill $GO_PID 2>/dev/null || true
    fi
    if [ -n "$PYTHON_PID" ]; then
        kill $PYTHON_PID 2>/dev/null || true
    fi
    echo "Shutdown complete"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Build Go engine if needed
if [ ! -f "./core_go/engine" ] || [ "./core_go/*.go" -nt "./core_go/engine" ]; then
    echo "Building Go execution engine..."
    cd core_go
    go build -o engine -ldflags="-s -w" *.go
    cd ..
fi

# Start Go execution engine
echo "Starting Go execution engine..."
if [ "$TASKSET_AVAILABLE" = true ]; then
    taskset -c $GO_CPUS ./core_go/engine $SYMBOL $MODE > logs/go_engine.log 2>&1 &
else
    ./core_go/engine $SYMBOL $MODE > logs/go_engine.log 2>&1 &
fi
GO_PID=$!
echo "Go engine PID: $GO_PID"

# Wait for shared memory to be created
echo "Waiting for shared memory initialization..."
sleep 2

if [ ! -f "$SHM_PATH" ]; then
    echo "Error: Shared memory not created. Check logs/go_engine.log"
    exit 1
fi

# Start Python AI brain
echo "Starting Python AI brain..."
cd brain_py
if [ "$TASKSET_AVAILABLE" = true ]; then
    taskset -c $PYTHON_CPUS python3 agent.py > ../logs/python_agent.log 2>&1 &
else
    python3 agent.py > ../logs/python_agent.log 2>&1 &
fi
PYTHON_PID=$!
cd ..
echo "Python brain PID: $PYTHON_PID"

echo ""
echo "=============================================="
echo "  HFT System Started Successfully"
echo "=============================================="
echo "Logs:"
echo "  Go Engine:    tail -f logs/go_engine.log"
echo "  Python Agent: tail -f logs/python_agent.log"
echo ""
echo "Press Ctrl+C to stop"
echo "=============================================="

# Monitor processes
while true; do
    if ! kill -0 $GO_PID 2>/dev/null; then
        echo "ERROR: Go engine has stopped!"
        cleanup
    fi
    if ! kill -0 $PYTHON_PID 2>/dev/null; then
        echo "ERROR: Python agent has stopped!"
        cleanup
    fi
    sleep 5
done
