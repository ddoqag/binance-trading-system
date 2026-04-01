"""
end_to_end_test.py - 完整端到端测试（Go引擎 + Python Agent）

测试真实组件的集成：
1. 启动 Go HFT 引擎（连接币安获取市场数据）
2. 启动 Python HFT Agent（读取SHM并生成交易决策）
3. 监控两者通过共享内存的通信
4. 验证决策流程：市场数据 -> Agent -> 决策 -> Go引擎
"""

import subprocess
import sys
import os
import time
import signal
import threading
from pathlib import Path

# 配置
SHM_PATH = "./data/hft_e2e_shm"
GO_ENGINE = "./core_go/hft_engine.exe"
AGENT_SCRIPT = "./brain_py/agent.py"
TEST_DURATION = 30  # 测试运行30秒

class EndToEndTest:
    def __init__(self):
        self.go_process = None
        self.agent_process = None
        self.running = False
        self.go_output = []
        self.agent_output = []
        self.stats = {
            "market_updates": 0,
            "decisions_made": 0,
            "acks_received": 0,
        }

    def _read_output(self, process, output_list, prefix):
        """读取子进程输出"""
        while self.running and process.poll() is None:
            try:
                line = process.stdout.readline()
                if line:
                    line = line.strip()
                    output_list.append(line)
                    print(f"[{prefix}] {line}")

                    # 统计
                    if prefix == "GO" and "Writing market data" in line:
                        self.stats["market_updates"] += 1
                    elif prefix == "AGENT" and "Decision made" in line:
                        self.stats["decisions_made"] += 1
                    elif prefix == "AGENT" and "Ack received" in line:
                        self.stats["acks_received"] += 1
            except:
                break

    def setup_shm(self):
        """设置共享内存文件"""
        os.makedirs(os.path.dirname(SHM_PATH), exist_ok=True)
        # 初始化共享内存文件
        with open(SHM_PATH, 'wb') as f:
            f.write(b'\x00' * 144)
        print(f"[TEST] Shared memory initialized: {SHM_PATH}")

    def start_go_engine(self):
        """启动 Go HFT 引擎"""
        print("[TEST] Starting Go HFT Engine...")

        # 修改引擎配置使用测试 SHM 路径
        env = os.environ.copy()
        env["HFT_SHM_PATH"] = os.path.abspath(SHM_PATH)
        # 添加代理设置（从 .env 文件读取）
        env["HTTP_PROXY"] = "http://127.0.0.1:7897"
        env["HTTPS_PROXY"] = "http://127.0.0.1:7897"

        self.go_process = subprocess.Popen(
            [GO_ENGINE, "btcusdt"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.path.dirname(__file__) or ".",
            env=env
        )

        # 启动输出读取线程
        thread = threading.Thread(
            target=self._read_output,
            args=(self.go_process, self.go_output, "GO")
        )
        thread.daemon = True
        thread.start()

        # 等待引擎启动
        time.sleep(2)

        if self.go_process.poll() is not None:
            print("[TEST] ERROR: Go engine failed to start!")
            return False

        print("[TEST] Go HFT Engine started")
        return True

    def start_python_agent(self):
        """启动 Python Agent"""
        print("[TEST] Starting Python HFT Agent...")

        # 创建修改后的 agent 脚本使用测试 SHM 路径
        agent_code = f'''
import sys
sys.path.insert(0, './brain_py')
import time
import numpy as np
from agent import HFTAgent

print("[AGENT] Starting HFT Agent with SHM: {SHM_PATH}")
agent = HFTAgent(shm_path="{SHM_PATH}")

print("[AGENT] Agent initialized, entering main loop...")
decision_count = 0
ack_count = 0
last_report = time.time()

try:
    while True:
        made_decision = agent.step()
        if made_decision:
            decision_count += 1
            print(f"[AGENT] Decision made #{{decision_count}}")

        # 定期报告
        if time.time() - last_report > 5:
            print(f"[AGENT] Status: {{decision_count}} decisions, trade_count={{agent.trade_count}}")
            last_report = time.time()

        # 训练
        agent.train()
        time.sleep(0.01)

except KeyboardInterrupt:
    print(f"[AGENT] Shutting down. Total decisions: {{decision_count}}")
'''

        self.agent_process = subprocess.Popen(
            [sys.executable, "-c", agent_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=os.path.dirname(__file__) or "."
        )

        # 启动输出读取线程
        thread = threading.Thread(
            target=self._read_output,
            args=(self.agent_process, self.agent_output, "AGENT")
        )
        thread.daemon = True
        thread.start()

        # 等待 agent 启动
        time.sleep(1)

        if self.agent_process.poll() is not None:
            print("[TEST] ERROR: Python agent failed to start!")
            return False

        print("[TEST] Python HFT Agent started")
        return True

    def run_test(self):
        """运行完整测试"""
        print("=" * 70)
        print("HFT System End-to-End Test")
        print("=" * 70)
        print(f"Duration: {TEST_DURATION} seconds")
        print(f"SHM Path: {SHM_PATH}")
        print()

        self.setup_shm()

        self.running = True

        # 启动组件
        if not self.start_go_engine():
            return False

        time.sleep(1)

        if not self.start_python_agent():
            self.stop()
            return False

        # 运行测试
        print()
        print("[TEST] Running end-to-end test...")
        print("-" * 70)

        try:
            time.sleep(TEST_DURATION)
        except KeyboardInterrupt:
            print("\n[TEST] Interrupted by user")

        print("-" * 70)
        print()

        # 停止组件
        self.stop()

        # 生成报告
        self.generate_report()

        return True

    def stop(self):
        """停止所有组件"""
        print("[TEST] Stopping components...")
        self.running = False

        # 停止 Python agent
        if self.agent_process and self.agent_process.poll() is None:
            if os.name == 'nt':
                # Windows: 使用 taskkill 来终止进程树
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.agent_process.pid)],
                              capture_output=True, check=False)
            else:
                self.agent_process.send_signal(signal.SIGTERM)
                try:
                    self.agent_process.wait(timeout=3)
                except:
                    self.agent_process.kill()
            print("[TEST] Python Agent stopped")

        # 停止 Go 引擎
        if self.go_process and self.go_process.poll() is None:
            if os.name == 'nt':
                # Windows: 使用 taskkill 来终止进程树
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(self.go_process.pid)],
                              capture_output=True, check=False)
            else:
                self.go_process.send_signal(signal.SIGTERM)
                try:
                    self.go_process.wait(timeout=3)
                except:
                    self.go_process.kill()
            print("[TEST] Go Engine stopped")

    def generate_report(self):
        """生成测试报告"""
        print()
        print("=" * 70)
        print("End-to-End Test Report")
        print("=" * 70)

        # 检查共享内存状态
        try:
            sys.path.insert(0, './brain_py')
            from shm_client import SHMClient

            with SHMClient(SHM_PATH) as client:
                state = client.read_state()
                if state:
                    print(f"[SHM] Final market state:")
                    print(f"      Seq: {state.seq}")
                    print(f"      Valid: {state.is_valid}")
                    print(f"      Best Bid: {state.best_bid:.2f}")
                    print(f"      Best Ask: {state.best_ask:.2f}")
                    print(f"      OFI: {state.ofi_signal:.4f}")
                else:
                    print("[SHM] Failed to read final state")
        except Exception as e:
            print(f"[SHM] Error reading state: {e}")

        print()
        print("[STATS] Test Statistics:")
        print(f"        Market updates: {self.stats['market_updates']}")
        print(f"        Decisions made: {self.stats['decisions_made']}")
        print(f"        Acks received: {self.stats['acks_received']}")

        # Go 引擎输出摘要
        go_errors = [line for line in self.go_output if "error" in line.lower() or "fail" in line.lower()]
        if go_errors:
            print()
            print("[GO] Errors found:")
            for line in go_errors[:5]:
                print(f"      {line}")

        # Agent 输出摘要
        agent_errors = [line for line in self.agent_output if "error" in line.lower() or "fail" in line.lower()]
        if agent_errors:
            print()
            print("[AGENT] Errors found:")
            for line in agent_errors[:5]:
                print(f"      {line}")

        print()
        print("=" * 70)

        # 清理
        if os.path.exists(SHM_PATH):
            try:
                os.remove(SHM_PATH)
            except:
                pass


if __name__ == "__main__":
    test = EndToEndTest()
    try:
        success = test.run_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"[TEST] Fatal error: {e}")
        import traceback
        traceback.print_exc()
        test.stop()
        sys.exit(1)
