#!/usr/bin/env python3
import sys
sys.path.insert(0, 'brain_py')
from shm_client import SHMClient

with SHMClient('./data/hft_trading_shm') as client:
    state = client.read_state()
    if state and state.is_valid:
        print(f'Market data: BTC ${state.best_bid:.2f}')
        print(f'Seq: {state.seq} | OFI: {state.ofi_signal:.4f}')
    else:
        print('Invalid state')
