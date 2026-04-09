#!/usr/bin/env python3
"""
HFT Trading System - Unified Entry Point Launcher
高频交易系统统一入口启动器

对应架构图:
- Legacy Stack (黄色)
- New Low-Latency Stack (绿色)
- External Systems (蓝色)
- Plugins (粉色)

Usage:
    python system_entry_points.py [component] [options]
"""

import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from enum import Enum, auto


class StackType(Enum):
    """架构栈类型"""
    LEGACY = auto()      # 传统架构 (黄色)
    NEW = auto()         # 新低延迟架构 (绿色)
    PLUGIN = auto()      # 插件层 (粉色)
    EXTERNAL = auto()    # 外部系统 (蓝色)
    ALL = auto()         # 全部启动


@dataclass
class EntryPoint:
    """程序入口定义"""
    name: str
    path: str
    stack: StackType
    description: str
    command: List[str]
    env_vars: Optional[dict] = None
    requires_api_key: bool = False
    port: Optional[int] = None


# ============================================================================
# 程序入口注册表
# ============================================================================

ENTRY_POINTS = {
    # ========================================================================
    # NEW LOW-LATENCY STACK (绿色)
    # ========================================================================
    
    # Go Core Engine - 低延迟核心引擎
    "go-engine": EntryPoint(
        name="Go Core Engine",
        path="./core_go/main_default.go",
        stack=StackType.NEW,
        description="标准Go HFT引擎 - 微秒级市场数据处理和订单执行",
        command=["go", "run", "./core_go/main_default.go"],
        port=8080
    ),
    
    "go-engine-http": EntryPoint(
        name="Go Core Engine (HTTP)",
        path="./core_go/main_with_http.go",
        stack=StackType.NEW,
        description="带HTTP API和Prometheus指标的Go引擎",
        command=["go", "run", "./core_go/main_with_http.go"],
        port=8080
    ),
    
    # Python Agents - Python智能体
    "agent-sac": EntryPoint(
        name="SAC RL Agent",
        path="./brain_py/agent.py",
        stack=StackType.NEW,
        description="SAC强化学习智能体 - 交易决策生成",
        command=["python", "./brain_py/agent.py"]
    ),
    
    "agent-integrator": EntryPoint(
        name="Live Integrator",
        path="./brain_py/live_integrator.py",
        stack=StackType.NEW,
        description="全脑组件实时集成 (含MoE)",
        command=["python", "./brain_py/live_integrator.py"]
    ),
    
    # New Orchestrator - 新编排器 (Hedge Fund OS)
    "orchestrator": EntryPoint(
        name="Hedge Fund OS Orchestrator",
        path="./hedge_fund_os/orchestrator.py",
        stack=StackType.NEW,
        description="对冲基金OS主编排器 - '大脑中的大脑'",
        command=["python", "./hedge_fund_os/orchestrator.py"],
        port=8000
    ),
    
    "demo-full": EntryPoint(
        name="P10 Full Demo",
        path="./hedge_fund_os/demo_full.py",
        stack=StackType.NEW,
        description="完整P10架构演示",
        command=["python", "./hedge_fund_os/demo_full.py"]
    ),
    
    "demo-monitoring": EntryPoint(
        name="P10 Monitoring Demo",
        path="./hedge_fund_os/demo_monitoring.py",
        stack=StackType.NEW,
        description="带Prometheus指标的P10演示",
        command=["python", "./hedge_fund_os/demo_monitoring.py"],
        port=8000
    ),
    
    # Rust Execution - Rust执行引擎
    "rust-engine": EntryPoint(
        name="Rust Execution Engine",
        path="./rust_execution/src/main.rs",
        stack=StackType.NEW,
        description="高性能Rust执行引擎 - 无需Python",
        command=["cargo", "run", "--release"],
        requires_api_key=True
    ),
    
    # Execution Core - 执行核心
    "exec-core": EntryPoint(
        name="Execution Core",
        path="./execution_core/order_state_machine.py",
        stack=StackType.NEW,
        description="订单状态机执行核心",
        command=["python", "./execution_core/order_state_machine.py"]
    ),
    
    # ========================================================================
    # LEGACY STACK (黄色)
    # ========================================================================
    
    # Live Orchestrators - 实时编排器
    "live-trader": EntryPoint(
        name="Live Trader",
        path="./start_live_trader.py",
        stack=StackType.LEGACY,
        description="实时交易 - 带PID锁和安全检查",
        command=["python", "./start_live_trader.py"],
        requires_api_key=True
    ),
    
    "data-collection": EntryPoint(
        name="Data Collection",
        path="./start_data_collection.py",
        stack=StackType.LEGACY,
        description="24小时信号统计收集",
        command=["python", "./start_data_collection.py"]
    ),
    
    "trading-system": EntryPoint(
        name="Trading System",
        path="./run_trading_system.py",
        stack=StackType.LEGACY,
        description="生产部署管理器 - 健康检查和配置验证",
        command=["python", "./run_trading_system.py"]
    ),
    
    # Research Pipeline - 研究管道
    "autoresearch": EntryPoint(
        name="AutoResearch Trading",
        path="./autoresearch_trading.py",
        stack=StackType.LEGACY,
        description="AutoResearch交易控制器 - 参数优化",
        command=["python", "./autoresearch_trading.py"]
    ),
    
    "live-autoresearch": EntryPoint(
        name="Live AutoResearch",
        path="./live_autoresearch.py",
        stack=StackType.LEGACY,
        description="实时自优化交易系统",
        command=["python", "./live_autoresearch.py"]
    ),
    
    "full-autoresearch": EntryPoint(
        name="Full AutoResearch Trading",
        path="./start_full_autoresearch_trading.py",
        stack=StackType.LEGACY,
        description="SelfEvolvingTrader + LiveAutoResearch完整集成",
        command=["python", "./start_full_autoresearch_trading.py"]
    ),
    
    # Factors & Models - 因子和模型
    "alpha-tribunal": EntryPoint(
        name="Alpha Tribunal",
        path="./brain_py/run_alpha_tribunal.py",
        stack=StackType.LEGACY,
        description="Alpha因子评估和仲裁系统",
        command=["python", "./brain_py/run_alpha_tribunal.py"]
    ),
    
    "phase1-backtest": EntryPoint(
        name="Phase 1 Backtest",
        path="./brain_py/run_phase1_backtest.py",
        stack=StackType.LEGACY,
        description="Phase 1回测 - 带Agent Registry",
        command=["python", "./brain_py/run_phase1_backtest.py"]
    ),
    
    # Legacy Strategies - 传统策略
    "mvp-trader": EntryPoint(
        name="MVP Trader",
        path="./brain_py/mvp_trader.py",
        stack=StackType.LEGACY,
        description="MVP HFT交易系统 - 队列优化、有毒流检测、价差捕获",
        command=["python", "./brain_py/mvp_trader.py"]
    ),
    
    # Backtest Engine - 回测引擎
    "backtest": EntryPoint(
        name="Backtest Engine",
        path="./backtest/backtest_engine.py",
        stack=StackType.LEGACY,
        description="事件驱动回测框架",
        command=["python", "./backtest/backtest_engine.py"]
    ),
    
    "paper-trading": EntryPoint(
        name="Paper Trading",
        path="./backtest/paper_trading.py",
        stack=StackType.LEGACY,
        description="模拟交易",
        command=["python", "./backtest/paper_trading.py"]
    ),
    
    # ========================================================================
    # PLUGINS (粉色)
    # ========================================================================
    
    "ab-test": EntryPoint(
        name="A/B Testing",
        path="./start_ab_test.py",
        stack=StackType.PLUGIN,
        description="模型和策略的A/B测试框架",
        command=["python", "./start_ab_test.py"]
    ),
    
    "weight-visualizer": EntryPoint(
        name="Weight Visualizer",
        path="./weight_visualizer.py",
        stack=StackType.PLUGIN,
        description="策略权重演化可视化",
        command=["python", "./weight_visualizer.py"]
    ),
    
    "stability-monitor": EntryPoint(
        name="Stability Monitor",
        path="./stability_monitor.py",
        stack=StackType.PLUGIN,
        description="系统稳定性监控",
        command=["python", "./stability_monitor.py"]
    ),
    
    "diagnose-price": EntryPoint(
        name="Price Diagnostics",
        path="./diagnose_price.py",
        stack=StackType.PLUGIN,
        description="价格诊断工具",
        command=["python", "./diagnose_price.py"]
    ),
    
    # ========================================================================
    # TESTING & VERIFICATION
    # ========================================================================
    
    "test-system": EntryPoint(
        name="System Test",
        path="./test_system.py",
        stack=StackType.PLUGIN,
        description="系统组件测试",
        command=["python", "./test_system.py"]
    ),
    
    "test-e2e": EntryPoint(
        name="E2E Test",
        path="./end_to_end_test.py",
        stack=StackType.PLUGIN,
        description="端到端集成测试",
        command=["python", "./end_to_end_test.py"],
        requires_api_key=True
    ),
    
    "test-shm": EntryPoint(
        name="SHM Verification",
        path="./shm_check.py",
        stack=StackType.PLUGIN,
        description="共享内存验证",
        command=["python", "./shm_check.py"]
    ),
}


# ============================================================================
# 启动脚本
# ============================================================================

class SystemLauncher:
    """系统启动器"""
    
    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        
    def list_components(self, stack: Optional[StackType] = None):
        """列出所有可用组件"""
        print("\n" + "="*70)
        print("HFT Trading System - Available Components")
        print("="*70)
        
        if stack is None or stack == StackType.NEW:
            print("\n🟢 NEW LOW-LATENCY STACK (绿色):")
            print("-" * 50)
            for key, ep in ENTRY_POINTS.items():
                if ep.stack == StackType.NEW:
                    port_info = f" [Port: {ep.port}]" if ep.port else ""
                    api_info = " [Requires API Key]" if ep.requires_api_key else ""
                    print(f"  {key:20} - {ep.description}{port_info}{api_info}")
        
        if stack is None or stack == StackType.LEGACY:
            print("\n🟡 LEGACY STACK (黄色):")
            print("-" * 50)
            for key, ep in ENTRY_POINTS.items():
                if ep.stack == StackType.LEGACY:
                    api_info = " [Requires API Key]" if ep.requires_api_key else ""
                    print(f"  {key:20} - {ep.description}{api_info}")
        
        if stack is None or stack == StackType.PLUGIN:
            print("\n🔴 PLUGINS (粉色):")
            print("-" * 50)
            for key, ep in ENTRY_POINTS.items():
                if ep.stack == StackType.PLUGIN:
                    print(f"  {key:20} - {ep.description}")
        
        print("\n" + "="*70)
        print("Usage: python system_entry_points.py <component> [args...]")
        print("="*70 + "\n")
    
    def start(self, component: str, extra_args: List[str] = None):
        """启动指定组件"""
        if component not in ENTRY_POINTS:
            print(f"❌ Unknown component: {component}")
            print(f"Run 'python system_entry_points.py --list' to see available components")
            return False
        
        ep = ENTRY_POINTS[component]
        
        print(f"\n🚀 Starting: {ep.name}")
        print(f"   Stack: {ep.stack.name}")
        print(f"   Path: {ep.path}")
        print(f"   Description: {ep.description}")
        print("-" * 50)
        
        # Check API keys if required
        if ep.requires_api_key:
            if not os.getenv("BINANCE_API_KEY") or not os.getenv("BINANCE_API_SECRET"):
                print("⚠️  Warning: BINANCE_API_KEY or BINANCE_API_SECRET not set!")
                print("   Set environment variables before running live trading.")
        
        # Build command
        cmd = ep.command.copy()
        if extra_args:
            cmd.extend(extra_args)
        
        # Set environment variables
        env = os.environ.copy()
        if ep.env_vars:
            env.update(ep.env_vars)
        
        # Start process
        try:
            process = subprocess.Popen(
                cmd,
                env=env,
                cwd=str(Path(__file__).parent)
            )
            self.processes.append(process)
            print(f"✅ Started with PID: {process.pid}")
            if ep.port:
                print(f"📡 Listening on port: {ep.port}")
            return True
        except Exception as e:
            print(f"❌ Failed to start: {e}")
            return False
    
    def start_stack(self, stack: StackType):
        """启动整个架构栈"""
        print(f"\n🚀 Starting {stack.name} stack...")
        
        components = [k for k, v in ENTRY_POINTS.items() if v.stack == stack]
        
        for component in components:
            self.start(component)
    
    def stop_all(self):
        """停止所有进程"""
        print("\n🛑 Stopping all processes...")
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
        print("✅ All processes stopped")


def main():
    parser = argparse.ArgumentParser(
        description="HFT Trading System Unified Entry Point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 列出所有组件
  python system_entry_points.py --list
  
  # 启动Go核心引擎
  python system_entry_points.py go-engine
  
  # 启动SAC智能体
  python system_entry_points.py agent-sac
  
  # 启动完整P10系统
  python system_entry_points.py orchestrator
  
  # 启动实时交易 (需要API密钥)
  python system_entry_points.py live-trader -- --symbol BTCUSDT
  
  # 启动回测
  python system_entry_points.py backtest
  
  # 运行系统测试
  python system_entry_points.py test-system
        """
    )
    
    parser.add_argument(
        "component",
        nargs="?",
        help="Component to start (use --list to see all)"
    )
    
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available components"
    )
    
    parser.add_argument(
        "--stack",
        choices=["new", "legacy", "plugin", "all"],
        help="Start all components in a stack"
    )
    
    parser.add_argument(
        "--symbol", "-s",
        default="BTCUSDT",
        help="Trading symbol (default: BTCUSDT)"
    )
    
    parser.add_argument(
        "--mode", "-m",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (default: paper)"
    )
    
    args, extra_args = parser.parse_known_args()
    
    launcher = SystemLauncher()
    
    if args.list:
        launcher.list_components()
        return
    
    if args.stack:
        stack_map = {
            "new": StackType.NEW,
            "legacy": StackType.LEGACY,
            "plugin": StackType.PLUGIN,
            "all": StackType.ALL
        }
        launcher.start_stack(stack_map[args.stack])
        return
    
    if not args.component:
        parser.print_help()
        return
    
    # Add symbol and mode to extra args if applicable
    if args.component in ["go-engine", "go-engine-http"]:
        extra_args = [args.symbol, args.mode] + extra_args
    
    launcher.start(args.component, extra_args)


if __name__ == "__main__":
    main()
