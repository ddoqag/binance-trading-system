"""
shm_client.py - Python Shared Memory Client for HFT System

Provides zero-copy communication between Python (AI brain) and Go (execution engine)
using mmap and sequence locks for lock-free synchronization.

Usage:
    client = SHMClient("/tmp/hft_trading_shm")

    # Read market data from Go
    state = client.read_state()

    # Write AI decision
    client.write_decision(
        action=TradingAction.JOIN_BID,
        target_position=0.5,
        target_size=0.01,
        confidence=0.85
    )
"""

import mmap
import struct
import os
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import IntEnum


class TradingAction(IntEnum):
    WAIT = 0
    JOIN_BID = 1
    JOIN_ASK = 2
    CROSS_BUY = 3
    CROSS_SELL = 4
    CANCEL = 5
    PARTIAL_EXIT = 6


class MarketRegime(IntEnum):
    UNKNOWN = 0
    TREND_UP = 1
    TREND_DOWN = 2
    RANGE = 3
    HIGH_VOL = 4
    LOW_VOL = 5


@dataclass
class MarketState:
    """Market data written by Go engine."""
    timestamp: int
    best_bid: float
    best_ask: float
    micro_price: float
    ofi_signal: float
    trade_imbalance: float
    bid_queue_pos: float
    ask_queue_pos: float
    seq: int
    seq_end: int

    @property
    def is_valid(self) -> bool:
        """Check if data is consistent (no tearing)."""
        return self.seq == self.seq_end

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2


@dataclass
class AIDecision:
    """AI decision written by Python brain."""
    action: TradingAction
    target_position: float
    target_size: float
    limit_price: float
    confidence: float
    regime: MarketRegime
    volatility_forecast: float
    timestamp: int


class SHMClient:
    """
    Shared memory client for HFT system.

    Implements sequence lock pattern for lock-free synchronization:
    1. Writer increments seq before writing
    2. Writer writes data
    3. Writer sets seq_end = seq after writing
    4. Reader checks seq == seq_end to ensure consistency
    """

    # Struct format for TradingSharedState (128 bytes)
    # q=long long, d=double, f=float, i=int
    # Line 0 (bytes 0-63): Market data from Go
    _FMT_LINE0 = "qqddddddffQ"  # 8+8+8+8+8+8+8+8+4+4+8 = 80 bytes - wait, let me recalculate

    # Updated format string for 144-byte struct (matches Go alignment)
    # Line 0 (bytes 0-71): Market data from Go (includes 4B padding)
    #   seq(8) + seq_end(8) + timestamp(8) + best_bid(8) + best_ask(8) +
    #   micro_price(8) + ofi_signal(8) + trade_imbalance(4) + bid_queue_pos(4) +
    #   ask_queue_pos(4) + padding(4) = 72 bytes
    # Line 1 (bytes 72-143): AI decision from Python (includes 8B padding)
    #   decision_seq(8) + decision_ack(8) + decision_timestamp(8) + target_position(8) +
    #   target_size(8) + limit_price(8) + confidence(4) + volatility_forecast(4) +
    #   action(4) + regime(4) + padding(8) = 72 bytes

    STRUCT_SIZE = 144

    # Offsets for direct field access - Cache Line 0 (Market Data)
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

    # Offsets for direct field access - Cache Line 1 (AI Decision)
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

    def __init__(self, path: str = "/tmp/hft_trading_shm"):
        self.path = path
        self._fd: Optional[int] = None
        self._mm: Optional[mmap.mmap] = None
        self._connect()

    def _connect(self):
        """Connect to shared memory segment."""
        # Create file if not exists
        if not os.path.exists(self.path):
            with open(self.path, 'wb') as f:
                f.write(b'\x00' * self.STRUCT_SIZE)

        self._fd = os.open(self.path, os.O_RDWR)

        # Ensure file is large enough
        size = os.fstat(self._fd).st_size
        if size < self.STRUCT_SIZE:
            os.ftruncate(self._fd, self.STRUCT_SIZE)

        self._mm = mmap.mmap(self._fd, self.STRUCT_SIZE, access=mmap.ACCESS_WRITE)

    def close(self):
        """Close shared memory connection."""
        if self._mm:
            self._mm.close()
            self._mm = None
        if self._fd:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _read_u64(self, offset: int) -> int:
        """Read unsigned 64-bit integer."""
        return struct.unpack_from("Q", self._mm, offset)[0]

    def _write_u64(self, offset: int, value: int):
        """Write unsigned 64-bit integer."""
        struct.pack_into("Q", self._mm, offset, value)

    def _read_i64(self, offset: int) -> int:
        """Read signed 64-bit integer."""
        return struct.unpack_from("q", self._mm, offset)[0]

    def _write_i64(self, offset: int, value: int):
        """Write signed 64-bit integer."""
        struct.pack_into("q", self._mm, offset, value)

    def _read_f64(self, offset: int) -> float:
        """Read 64-bit float."""
        return struct.unpack_from("d", self._mm, offset)[0]

    def _write_f64(self, offset: int, value: float):
        """Write 64-bit float."""
        struct.pack_into("d", self._mm, offset, value)

    def _read_f32(self, offset: int) -> float:
        """Read 32-bit float."""
        return struct.unpack_from("f", self._mm, offset)[0]

    def _write_f32(self, offset: int, value: float):
        """Write 32-bit float."""
        struct.pack_into("f", self._mm, offset, value)

    def _read_i32(self, offset: int) -> int:
        """Read 32-bit integer."""
        return struct.unpack_from("i", self._mm, offset)[0]

    def _write_i32(self, offset: int, value: int):
        """Write 32-bit integer."""
        struct.pack_into("i", self._mm, offset, value)

    def read_state(self, max_retries: int = 100) -> Optional[MarketState]:
        """
        Read market state with sequence lock validation.

        Retries if data is being written (seq != seq_end).

        Args:
            max_retries: Maximum attempts to get consistent read

        Returns:
            MarketState if successful, None if max retries exceeded
        """
        for _ in range(max_retries):
            seq_before = self._read_u64(self.OFFSET_SEQ)

            # Read all data from cache line 0
            timestamp = self._read_i64(self.OFFSET_TIMESTAMP)
            best_bid = self._read_f64(self.OFFSET_BEST_BID)
            best_ask = self._read_f64(self.OFFSET_BEST_ASK)
            micro_price = self._read_f64(self.OFFSET_MICRO_PRICE)
            ofi = self._read_f64(self.OFFSET_OFI)
            trade_imb = self._read_f32(self.OFFSET_TRADE_IMBALANCE)
            bid_queue = self._read_f32(self.OFFSET_BID_QUEUE)
            ask_queue = self._read_f32(self.OFFSET_ASK_QUEUE)

            seq_after = self._read_u64(self.OFFSET_SEQ_END)

            # Verify consistency
            if seq_before == seq_after:
                return MarketState(
                    timestamp=timestamp,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    micro_price=micro_price,
                    ofi_signal=ofi,
                    trade_imbalance=trade_imb,
                    bid_queue_pos=bid_queue,
                    ask_queue_pos=ask_queue,
                    seq=seq_before,
                    seq_end=seq_after
                )

        return None

    def write_decision(self, action: TradingAction, target_position: float,
                       target_size: float, confidence: float,
                       limit_price: float = 0.0,
                       regime: MarketRegime = MarketRegime.UNKNOWN,
                       volatility_forecast: float = 0.0):
        """
        Write AI decision to shared memory.

        Uses sequence lock to ensure atomic write.
        Go engine will read decision_seq and acknowledge by setting decision_ack.
        """
        # Increment sequence to indicate new decision
        seq = self._read_u64(self.OFFSET_DECISION_SEQ)
        new_seq = seq + 1
        self._write_u64(self.OFFSET_DECISION_SEQ, new_seq)

        # Write all fields to cache line 1
        self._write_i64(self.OFFSET_DECISION_TS, time.time_ns())
        self._write_f64(self.OFFSET_TARGET_POS, target_position)
        self._write_f64(self.OFFSET_TARGET_SIZE, target_size)
        self._write_f64(self.OFFSET_LIMIT_PRICE, limit_price)
        self._write_f32(self.OFFSET_CONFIDENCE, confidence)
        self._write_f32(self.OFFSET_VOL_FORECAST, volatility_forecast)
        self._write_i32(self.OFFSET_ACTION, int(action))
        self._write_i32(self.OFFSET_REGIME, int(regime))

        # Note: decision_ack is written by Go engine, not Python

    def wait_for_ack(self, timeout_ms: int = 100) -> bool:
        """
        Wait for Go engine to acknowledge decision.

        Returns:
            True if acknowledged, False if timeout
        """
        seq = self._read_u64(self.OFFSET_DECISION_SEQ)
        start = time.time()
        timeout_sec = timeout_ms / 1000.0

        while time.time() - start < timeout_sec:
            ack = self._read_u64(self.OFFSET_DECISION_ACK)
            if ack == seq:
                return True
            time.sleep(0.001)  # 1ms sleep

        return False


class SHMReader:
    """
    Read-only shared memory client for monitoring/observation.

    This is safer for tools that only need to observe state without
    writing decisions.
    """

    def __init__(self, path: str = "/tmp/hft_trading_shm"):
        self.path = path
        self._fd = os.open(path, os.O_RDONLY)
        self._mm = mmap.mmap(self._fd, SHMClient.STRUCT_SIZE, access=mmap.ACCESS_READ)

    def read_state(self) -> Optional[MarketState]:
        """Read current market state (read-only)."""
        # Same implementation as SHMClient but without write methods
        client = SHMClient.__new__(SHMClient)
        client._mm = self._mm
        return client.read_state()

    def close(self):
        if self._mm:
            self._mm.close()
            self._mm = None
        if self._fd:
            os.close(self._fd)
            self._fd = None


# Simple test
if __name__ == "__main__":
    import sys

    print("Testing SHM Client...")

    with SHMClient() as client:
        # Test write decision
        client.write_decision(
            action=TradingAction.JOIN_BID,
            target_position=0.5,
            target_size=0.01,
            confidence=0.85,
            regime=MarketRegime.TREND_UP
        )
        print("Written decision to shared memory")

        # Read back state
        state = client.read_state()
        if state:
            print(f"Read state: seq={state.seq}, valid={state.is_valid}")
            print(f"  Prices: bid={state.best_bid}, ask={state.best_ask}")
            print(f"  OFI: {state.ofi_signal}")
        else:
            print("Failed to read consistent state")

    print("Test complete")
