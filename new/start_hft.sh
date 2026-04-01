#!/bin/bash
# start_hft.sh - Start HFT System in Git Bash

set -e

SYMBOL=${1:-btcusdt}
MODE=${2:-paper}
SHM_PATH="./data/hft_trading_shm"

echo "============================================"
echo "   HFT Trading System Startup"
echo "============================================"
echo "Symbol: $SYMBOL"
echo "Mode: $MODE"
echo "============================================"

# Clean up previous shared memory
if [ -f "$SHM_PATH" ]; then
    echo "Cleaning up previous shared memory..."
    rm -f "$SHM_PATH"
fi

# Create necessary directories
mkdir -p logs data checkpoints

# Initialize shared memory file
/c/Python314/python.exe -c "
import os
os.makedirs('./data', exist_ok=True)
with open('$SHM_PATH', 'wb') as f:
    f.write(b'\\x00' * 144)
print('Shared memory initialized')
"

# Export environment variables
export HFT_SHM_PATH="$(pwd)/$SHM_PATH"
export HTTP_PROXY="http://127.0.0.1:7897"
export HTTPS_PROXY="http://127.0.0.1:7897"

echo ""
echo "Starting Go HFT Engine..."
cd core_go
./hft_engine.exe "$SYMBOL" "$MODE" > ../logs/go_engine.log 2>&1 &
GO_PID=$!
cd ..
echo "Go Engine started (PID: $GO_PID)"

# Wait for engine to initialize
echo "Waiting for engine initialization..."
sleep 3

# Check if Go engine is running
if ! kill -0 $GO_PID 2>/dev/null; then
    echo "ERROR: Go engine failed to start!"
    cat logs/go_engine.log
    exit 1
fi

echo ""
echo "Starting Python HFT Agent..."
cd brain_py
/c/Python314/python.exe agent.py > ../logs/python_agent.log 2>&1 &
AGENT_PID=$!
cd ..
echo "Python Agent started (PID: $AGENT_PID)"

sleep 2

# Check if Python agent is running
if ! kill -0 $AGENT_PID 2>/dev/null; then
    echo "ERROR: Python agent failed to start!"
    cat logs/python_agent.log
    kill $GO_PID 2>/dev/null
    exit 1
fi

echo ""
echo "============================================"
echo "   HFT System Started Successfully"
echo "============================================"
echo "Logs:"
echo "  Go Engine:    tail -f logs/go_engine.log"
echo "  Python Agent: tail -f logs/python_agent.log"
echo ""
echo "Processes:"
echo "  Go Engine:    PID $GO_PID"
echo "  Python Agent: PID $AGENT_PID"
echo ""
echo "Press Ctrl+C to stop"
echo "============================================"

# Save PIDs for cleanup
echo $GO_PID > .go_pid
echo $AGENT_PID > .agent_pid

# Monitor loop
trap 'echo ""; echo "Shutting down HFT System..."; kill $AGENT_PID 2>/dev/null; sleep 1; kill $GO_PID 2>/dev/null; rm -f .go_pid .agent_pid; echo "Shutdown complete"; exit 0' INT

while true; do
    if ! kill -0 $GO_PID 2>/dev/null; then
        echo "ERROR: Go engine has stopped!"
        kill $AGENT_PID 2>/dev/null
        rm -f .go_pid .agent_pid
        exit 1
    fi
    if ! kill -0 $AGENT_PID 2>/dev/null; then
        echo "ERROR: Python agent has stopped!"
        kill $GO_PID 2>/dev/null
        rm -f .go_pid .agent_pid
        exit 1
    fi
    sleep 5
done
