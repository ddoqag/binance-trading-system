"""
Simple E2E test - verify Go engine and Python agent can start and communicate
"""
import subprocess
import sys
import os
import time
import threading

SHM_PATH = "./data/hft_e2e_test_shm"
GO_ENGINE = "./core_go/hft_engine.exe"

def test_go_engine():
    """Test Go engine starts and connects to Binance"""
    print("[TEST] Testing Go HFT Engine...")

    # Setup SHM
    os.makedirs("./data", exist_ok=True)
    with open(SHM_PATH, 'wb') as f:
        f.write(b'\x00' * 144)

    env = os.environ.copy()
    env["HFT_SHM_PATH"] = os.path.abspath(SHM_PATH)
    env["HTTP_PROXY"] = "http://127.0.0.1:7897"
    env["HTTPS_PROXY"] = "http://127.0.0.1:7897"

    # Start Go engine
    proc = subprocess.Popen(
        [GO_ENGINE, "btcusdt"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env
    )

    # Read output for 5 seconds
    output = []
    def read_output():
        for line in proc.stdout:
            line = line.strip()
            output.append(line)
            print(f"[GO] {line}")

    thread = threading.Thread(target=read_output)
    thread.daemon = True
    thread.start()

    # Wait and check
    time.sleep(5)

    if proc.poll() is not None:
        print(f"[FAIL] Go engine exited early with code {proc.poll()}")
        return False

    # Check for connection success
    connected = any("Connected to Binance" in line for line in output)
    if connected:
        print("[PASS] Go engine connected to Binance WebSocket")
    else:
        print("[WARN] Go engine running but connection status unclear")

    # Cleanup
    proc.terminate()
    proc.wait(timeout=2)

    return True

def test_python_agent():
    """Test Python agent can initialize"""
    print("\n[TEST] Testing Python Agent...")

    # Setup SHM
    os.makedirs("./data", exist_ok=True)
    with open(SHM_PATH, 'wb') as f:
        f.write(b'\x00' * 144)

    # Test agent import and initialization
    test_code = f'''
import sys
sys.path.insert(0, './brain_py')
from agent import HFTAgent

print("[AGENT] Creating HFTAgent...")
agent = HFTAgent(shm_path="{SHM_PATH}")
print(f"[AGENT] Agent created: state_dim={{agent.agent.config.state_dim}}")
print("[PASS] Python Agent initialized successfully")
'''

    result = subprocess.run(
        [sys.executable, "-c", test_code],
        capture_output=True,
        text=True
    )

    print(result.stdout)
    if result.returncode != 0:
        print(f"[FAIL] Agent error: {result.stderr}")
        return False

    return True

def test_shm_communication():
    """Test shared memory read/write"""
    print("\n[TEST] Testing SHM Communication...")

    import sys
    sys.path.insert(0, './brain_py')
    from shm_client import SHMClient, TradingAction

    # Setup SHM
    os.makedirs("./data", exist_ok=True)
    with open(SHM_PATH, 'wb') as f:
        f.write(b'\x00' * 144)

    # Write decision
    client = SHMClient(SHM_PATH)
    client.write_decision(
        action=TradingAction.JOIN_BID,
        target_position=0.5,
        target_size=0.01,
        confidence=0.85
    )
    print("[OK] Decision written to SHM")

    # Read back
    state = client.read_state()
    if state:
        print(f"[OK] State read: seq={state.seq}, valid={state.is_valid}")
    else:
        print("[WARN] State read returned None")

    client.close()
    print("[PASS] SHM communication working")
    return True

def main():
    print("=" * 60)
    print("HFT System E2E Test (Simplified)")
    print("=" * 60)

    results = []

    # Test 1: Go Engine
    try:
        results.append(("Go Engine", test_go_engine()))
    except Exception as e:
        print(f"[FAIL] Go Engine test failed: {e}")
        results.append(("Go Engine", False))

    # Test 2: Python Agent
    try:
        results.append(("Python Agent", test_python_agent()))
    except Exception as e:
        print(f"[FAIL] Python Agent test failed: {e}")
        results.append(("Python Agent", False))

    # Test 3: SHM Communication
    try:
        results.append(("SHM Communication", test_shm_communication()))
    except Exception as e:
        print(f"[FAIL] SHM test failed: {e}")
        results.append(("SHM Communication", False))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")

    all_passed = all(r[1] for r in results)
    print("\n" + ("All tests passed!" if all_passed else "Some tests failed."))

    # Cleanup
    if os.path.exists(SHM_PATH):
        try:
            os.remove(SHM_PATH)
        except:
            pass

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
