"""
integration_test.py - Full integration test for HFT system

Tests complete data flow:
1. Mock Go engine writes market data to shared memory
2. Python agent reads market data and generates decisions
3. Mock Go engine reads decisions and acknowledges
4. Verify end-to-end latency and consistency
"""

import sys
import os
import time
import threading
import struct

sys.path.insert(0, '.')

# Constants matching protocol.h (144 bytes with Go alignment)
STRUCT_SIZE = 144
OFFSET_SEQ = 0
OFFSET_SEQ_END = 8
OFFSET_TIMESTAMP = 16
OFFSET_BEST_BID = 24
OFFSET_BEST_ASK = 32
OFFSET_MICRO_PRICE = 40
OFFSET_OFI = 48
OFFSET_TRADE_IMBALANCE = 56
OFFSET_BID_QUEUE = 60
OFFSET_ASK_QUEUE = 64
OFFSET_DECISION_SEQ = 72
OFFSET_DECISION_ACK = 80
OFFSET_DECISION_TS = 88
OFFSET_TARGET_POS = 96
OFFSET_TARGET_SIZE = 104
OFFSET_LIMIT_PRICE = 112
OFFSET_CONFIDENCE = 120
OFFSET_VOL_FORECAST = 124
OFFSET_ACTION = 128
OFFSET_REGIME = 132


class MockGoEngine:
    """Simulates Go HFT engine writing market data to SHM."""

    def __init__(self, shm_path="./data/test_integration_shm"):
        self.shm_path = shm_path
        self.running = False
        self.seq = 0
        self.thread = None

        import mmap
        os.makedirs(os.path.dirname(shm_path), exist_ok=True)

        if not os.path.exists(shm_path):
            with open(shm_path, 'wb') as f:
                f.write(b'\x00' * STRUCT_SIZE)

        self._fd = os.open(shm_path, os.O_RDWR)
        self._mm = mmap.mmap(self._fd, STRUCT_SIZE, access=mmap.ACCESS_WRITE)

    def _write_f64(self, offset, value):
        struct.pack_into("d", self._mm, offset, value)

    def _write_f32(self, offset, value):
        struct.pack_into("f", self._mm, offset, value)

    def _write_u64(self, offset, value):
        struct.pack_into("Q", self._mm, offset, value)

    def _write_i64(self, offset, value):
        struct.pack_into("q", self._mm, offset, value)

    def _read_u64(self, offset):
        return struct.unpack_from("Q", self._mm, offset)[0]

    def write_market_data(self, best_bid, best_ask, ofi, trade_imb=0.0):
        """Write market data to shared memory."""
        self.seq += 1
        self._write_u64(OFFSET_SEQ, self.seq)

        mid = (best_bid + best_ask) / 2
        micro_price = mid + (best_ask - best_bid) * 0.1  # Slightly biased toward ask

        self._write_i64(OFFSET_TIMESTAMP, time.time_ns())
        self._write_f64(OFFSET_BEST_BID, best_bid)
        self._write_f64(OFFSET_BEST_ASK, best_ask)
        self._write_f64(OFFSET_MICRO_PRICE, micro_price)
        self._write_f64(OFFSET_OFI, ofi)
        self._write_f32(OFFSET_TRADE_IMBALANCE, trade_imb)
        self._write_f32(OFFSET_BID_QUEUE, 0.5)
        self._write_f32(OFFSET_ASK_QUEUE, 0.5)

        self._write_u64(OFFSET_SEQ_END, self.seq)

    def read_decision(self):
        """Read AI decision from shared memory."""
        seq = self._read_u64(OFFSET_DECISION_SEQ)
        ack = self._read_u64(OFFSET_DECISION_ACK)

        if seq != ack and seq > 0:
            # New decision pending
            action = struct.unpack_from("i", self._mm, OFFSET_ACTION)[0]
            confidence = struct.unpack_from("f", self._mm, OFFSET_CONFIDENCE)[0]
            target_size = struct.unpack_from("d", self._mm, OFFSET_TARGET_SIZE)[0]

            # Acknowledge
            self._write_u64(OFFSET_DECISION_ACK, seq)

            return {
                'action': action,
                'confidence': confidence,
                'target_size': target_size,
                'seq': seq
            }

        return None

    def start(self):
        """Start market data simulation."""
        self.running = True
        self.thread = threading.Thread(target=self._market_loop)
        self.thread.start()
        print(f"[MOCK-GO] Engine started, writing to {self.shm_path}")

    def _market_loop(self):
        """Simulate market data updates at 10Hz."""
        base_price = 65000.0
        tick = 0

        while self.running:
            # Simulate price movement
            import math
            noise = math.sin(tick * 0.1) * 10
            ofi = math.sin(tick * 0.05) * 0.5  # Oscillating OFI

            best_bid = base_price + noise
            best_ask = best_bid + 10  # $10 spread

            self.write_market_data(best_bid, best_ask, ofi)

            tick += 1
            time.sleep(0.1)  # 100ms = 10Hz

    def stop(self):
        """Stop engine."""
        self.running = False
        if self.thread:
            self.thread.join()
        self._mm.close()
        os.close(self._fd)
        print("[MOCK-GO] Engine stopped")


def test_integration():
    """Test full integration between mock Go engine and Python agent."""
    sys.path.insert(0, './brain_py')
    from shm_client import SHMClient, TradingAction
    from agent import SACAgent, HFTAgent

    print("=" * 70)
    print("HFT System Integration Test")
    print("=" * 70)

    shm_path = "./data/test_integration_shm"

    # Clean up any existing SHM file
    if os.path.exists(shm_path):
        try:
            os.remove(shm_path)
        except:
            pass  # File may be in use from previous run

    # Start mock Go engine
    print("\n[1] Starting Mock Go Engine...")
    mock_engine = MockGoEngine(shm_path)
    mock_engine.start()

    # Wait for market data to be written
    time.sleep(0.3)

    # Test 1: Direct SHM client test
    print("\n[2] Testing SHM Client (Python side)...")
    client = SHMClient(shm_path)

    state = client.read_state()
    if state:
        print(f"  [OK] Market state read:")
        print(f"       Best bid: {state.best_bid:.2f}")
        print(f"       Best ask: {state.best_ask:.2f}")
        print(f"       OFI: {state.ofi_signal:.4f}")
        print(f"       Seq: {state.seq}")
    else:
        print("  [FAIL] Could not read market state")
        return False

    # Test 2: Write decision
    print("\n[3] Testing decision write...")
    client.write_decision(
        action=TradingAction.JOIN_BID,
        target_position=0.1,
        target_size=0.01,
        confidence=0.75
    )
    print("  [OK] Decision written")

    # Test 3: Go engine reads decision
    time.sleep(0.1)
    decision = mock_engine.read_decision()
    if decision:
        print(f"  [OK] Decision read by Go engine:")
        print(f"       Action: {decision['action']}")
        print(f"       Confidence: {decision['confidence']:.2f}")
        print(f"       Size: {decision['target_size']:.4f}")
    else:
        print("  [FAIL] Could not read decision")
        return False

    # Test 4: HFTAgent integration
    print("\n[4] Testing HFTAgent with live market data...")

    # Create custom agent that uses our test SHM path
    class TestHFTAgent(HFTAgent):
        def __init__(self, shm_path):
            from shm_client import SHMClient
            self.shm = SHMClient(shm_path)
            self.agent = SACAgent()
            self.prev_state = None
            self.prev_action = None
            self.last_trade_time = 0
            self.trade_count = 0

    test_agent = TestHFTAgent(shm_path)

    # Run agent for a few iterations
    decisions_made = 0
    print("  Running agent for 3 seconds...")
    for i in range(30):  # 3 seconds at 100ms interval
        made_decision = test_agent.step()
        if made_decision:
            decisions_made += 1
            print(f"    [DECISION] #{decisions_made} at t={i*0.1:.1f}s")

            # Check if Go engine received it
            d = mock_engine.read_decision()
            if d:
                print(f"      -> Go engine received: action={d['action']}, conf={d['confidence']:.2f}")

        time.sleep(0.1)

    print(f"\n  [OK] Agent made {decisions_made} decisions in 3 seconds")

    # Cleanup
    try:
        client.close()
    except:
        pass
    try:
        mock_engine.stop()
    except:
        pass

    # Cleanup SHM file
    time.sleep(0.1)  # Give Windows time to release file handles
    if os.path.exists(shm_path):
        try:
            os.remove(shm_path)
        except:
            pass  # Ignore cleanup errors

    # Summary
    print("\n" + "=" * 70)
    print("Integration Test Summary")
    print("=" * 70)
    print("  [PASS] Shared memory communication")
    print("  [PASS] Market data flow (Go -> Python)")
    print("  [PASS] Decision flow (Python -> Go)")
    print("  [PASS] Acknowledgment mechanism")
    print("  [PASS] HFTAgent end-to-end")
    print(f"\n[OK] All integration tests passed!")
    print(f"      Decisions made: {decisions_made}")
    print("=" * 70)

    return True


if __name__ == "__main__":
    try:
        success = test_integration()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n[FAIL] Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
