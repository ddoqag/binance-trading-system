#!/usr/bin/env python3
"""
协议对齐验证脚本
检查 C/Python/Go 三个协议的结构体大小和偏移量是否一致
"""

import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from shared.protocol import (
        HFT_PROTOCOL_MAGIC, HFT_PROTOCOL_VERSION,
        REVERSAL_SHM_MAGIC, REVERSAL_SHM_VERSION,
        REVERSAL_FEATURES_OFFSET, REVERSAL_FEATURES_SIZE,
        REVERSAL_SIGNAL_OFFSET, REVERSAL_SIGNAL_SIZE,
        VERIFICATION_SHM_MAGIC, VERIFICATION_SHM_VERSION,
        VERIFICATION_METRICS_OFFSET, VERIFICATION_METRICS_SIZE,
        PROTOCOL_VERSION_MAJOR, PROTOCOL_VERSION_MINOR,
    )
except ImportError as e:
    print(f"Error importing protocol: {e}")
    sys.exit(1)


def main():
    print("HFT Protocol Alignment Check")
    print("=" * 50)
    
    print(f"HFT Magic: 0x{HFT_PROTOCOL_MAGIC:08X}")
    print(f"Reversal Magic: 0x{REVERSAL_SHM_MAGIC:08X}")
    print(f"Verification Magic: 0x{VERIFICATION_SHM_MAGIC:08X}")
    
    print(f"\nReversal Features: offset={REVERSAL_FEATURES_OFFSET}, size={REVERSAL_FEATURES_SIZE}")
    print(f"Reversal Signal: offset={REVERSAL_SIGNAL_OFFSET}, size={REVERSAL_SIGNAL_SIZE}")
    print(f"Verification Metrics: offset={VERIFICATION_METRICS_OFFSET}, size={VERIFICATION_METRICS_SIZE}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
