#!/usr/bin/env python3
"""
AST + Static Analysis Tool for Binance HFT System
Extracts real import/call relationships from Python and Go code.
"""
import ast
import os
import sys
import json
import re
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).parent.resolve()

def analyze_python_imports_and_calls(directory: Path):
    """Analyze all .py files under directory for imports and function calls."""
    results = {
        "files": {},
        "imports_graph": defaultdict(list),
        "call_graph": defaultdict(lambda: defaultdict(set)),
        "entry_points": [],
        "classes": {},
        "functions": {},
    }

    for py_file in directory.rglob("*.py"):
        rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"), filename=str(py_file))
        except SyntaxError:
            continue

        file_imports = []
        file_calls = defaultdict(set)
        file_classes = []
        file_functions = []
        has_main = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    file_imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                file_imports.append(module)
            elif isinstance(node, ast.ClassDef):
                file_classes.append(node.name)
            elif isinstance(node, ast.FunctionDef):
                file_functions.append(node.name)
            elif isinstance(node, ast.Call):
                # Try to extract call target name
                if isinstance(node.func, ast.Name):
                    file_calls["global"].add(node.func.id)
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    file_calls[node.func.value.id].add(node.func.attr)
            elif isinstance(node, ast.If):
                # Check for if __name__ == '__main__':
                if (
                    isinstance(node.test, ast.Compare)
                    and isinstance(node.test.left, ast.Name)
                    and node.test.left.id == "__name__"
                ):
                    has_main = True

        results["files"][rel_path] = {
            "imports": file_imports,
            "calls": {k: list(v) for k, v in file_calls.items()},
            "classes": file_classes,
            "functions": file_functions,
            "has_main": has_main,
        }

        if has_main:
            results["entry_points"].append(rel_path)

        for imp in file_imports:
            results["imports_graph"][rel_path].append(imp)

        for scope, calls in file_calls.items():
            for call in calls:
                results["call_graph"][rel_path][scope].add(call)

        if file_classes:
            results["classes"][rel_path] = file_classes
        if file_functions:
            results["functions"][rel_path] = file_functions

    # Convert sets to lists for JSON
    results["call_graph"] = {
        k: {kk: list(vv) for kk, vv in v.items()}
        for k, v in results["call_graph"].items()
    }
    results["imports_graph"] = dict(results["imports_graph"])

    return results


def analyze_go_imports_and_calls(directory: Path):
    """Basic regex-based analysis for Go files."""
    results = {
        "files": {},
        "imports_graph": defaultdict(list),
        "func_calls": defaultdict(set),
        "entry_points": [],
        "structs": {},
        "interfaces": {},
        "functions": {},
    }

    for go_file in directory.rglob("*.go"):
        rel_path = go_file.relative_to(PROJECT_ROOT).as_posix()
        content = go_file.read_text(encoding="utf-8", errors="ignore")

        # Imports
        imports = re.findall(r'"([^"]+)"', content)
        std_imports = [i for i in imports if "." not in i and "/" not in i]
        ext_imports = [i for i in imports if "." in i or "/" in i]

        # Function calls: funcName(
        calls = set(re.findall(r'\b([A-Z][A-Za-z0-9_]*)\s*\(', content))
        # Filter out struct literals and type assertions roughly
        calls = {c for c in calls if c not in {
            "make", "new", "len", "cap", "append", "copy", "delete",
            "close", "panic", "recover", "print", "println", "error"
        }}

        # Structs
        structs = re.findall(r'type\s+([A-Z][A-Za-z0-9_]*)\s+struct', content)
        # Interfaces
        interfaces = re.findall(r'type\s+([A-Z][A-Za-z0-9_]*)\s+interface', content)
        # Functions (including methods)
        funcs = re.findall(r'func\s+(?:\([^)]+\)\s+)?([A-Z][A-Za-z0-9_]*|\bmain\b)', content)

        has_main = "func main()" in content

        results["files"][rel_path] = {
            "std_imports": std_imports,
            "ext_imports": ext_imports,
            "structs": structs,
            "interfaces": interfaces,
            "functions": funcs,
            "has_main": has_main,
        }

        if has_main:
            results["entry_points"].append(rel_path)

        results["imports_graph"][rel_path] = ext_imports
        results["func_calls"][rel_path] = list(calls)
        if structs:
            results["structs"][rel_path] = structs
        if interfaces:
            results["interfaces"][rel_path] = interfaces
        if funcs:
            results["functions"][rel_path] = funcs

    results["imports_graph"] = dict(results["imports_graph"])
    results["func_calls"] = {k: list(v) for k, v in results["func_calls"].items()}

    return results


def find_core_interfaces(py_results, go_results):
    """Identify the most critical interfaces based on naming and centrality."""
    interfaces = []

    # Go HTTP API endpoints from main_with_http.go
    interfaces.append({
        "name": "Go Engine HTTP API",
        "location": "core_go/main_with_http.go",
        "endpoints": [
            "GET /api/v1/status",
            "GET /api/v1/market/book",
            "POST /api/v1/orders",
            "DELETE /api/v1/orders/{id}",
            "GET /api/v1/position",
            "GET /api/v1/risk/stats",
            "GET /api/v1/system/metrics",
        ],
        "input": "HTTP JSON / REST",
        "output": "JSON (market data, order ack, position, risk stats)",
    })

    # Python SHM interfaces
    interfaces.append({
        "name": "Trading SHM (Shared Memory)",
        "location": "brain_py/shm_client.py <-> core_go/shm_manager.go",
        "input": "Python TradingAction struct via mmap",
        "output": "Go engine reads action + writes MarketState",
    })

    interfaces.append({
        "name": "Event SHM (Shared Memory)",
        "location": "brain_py/shm_event_client.py <-> core_go/engine.go (Event ring buffer)",
        "input": "Go engine writes fill/position sync events",
        "output": "Python consumes events",
    })

    # Binance API client
    interfaces.append({
        "name": "Binance Live API Client",
        "location": "core_go/live_api_client.go",
        "input": "API Key, API Secret, order requests",
        "output": "REST responses, WebSocket user data stream events",
    })

    # Strategy bridge
    interfaces.append({
        "name": "StrategyBridge",
        "location": "brain_py/strategy_bridge.py",
        "input": "orderbook dict {bids, asks, mid_price, spread}",
        "output": "signal dict {direction, strength, confidence, regime, strategy}",
    })

    # Execution bridge
    interfaces.append({
        "name": "ExecutionBridge",
        "location": "brain_py/execution_bridge.py",
        "input": "signal side, regime, book",
        "output": "reprice orders list [{side, size, price}] + lifecycle tracking",
    })

    return interfaces


def extract_startup_shutdown(py_results, go_results):
    """Map out the startup and shutdown sequences."""
    startup = {
        "batch": "start_live_margin.bat DOGEUSDT",
        "phases": [
            "Phase 0: Load .env, validate API keys, check USE_TESTNET=false",
            "Phase 1: preflight_profit_guard.py --symbol DOGEUSDT",
            "Phase 2: Clean old SHM files and emergency markers",
            "Phase 3: Start Go Engine (hft_engine_http.exe DOGEUSDT live margin)",
            "Phase 3a: Go loads .env, creates LiveAPIClient, starts HTTP server :8080",
            "Phase 3b: Go connects Binance WebSocket (depth, trade, ticker)",
            "Phase 3c: Go starts UserDataStreamManager for order lifecycle",
            "Phase 4: Poll http://127.0.0.1:8080/api/v1/status until ready",
            "Phase 5: Start Python MVP Trader (mvp_trader_live.py --symbol DOGEUSDT --mode live)",
            "Phase 5a: Python prints REAL MONEY warning",
            "Phase 5b: Python initializes SHMClient + EventSHMClient",
            "Phase 5c: Python waits for Go engine via SHM market data",
            "Phase 5d: Python queries margin account balance",
            "Phase 5e: Python initializes StrategyBridge, ExecutionBridge, MVPTrader",
            "Phase 6: Start PnL Watchdog (pnl_watchdog.py)",
        ],
    }

    shutdown = {
        "batch": "stop_hft_margin.bat",
        "steps": [
            "Read PIDs from hft_margin.pids and hft_engine.pid",
            "Kill Python trader and watchdog processes",
            "Kill Go engine process",
            "Write emergency_stop_marker if kill-switch triggered",
            "Clean up SHM files",
        ],
    }

    return {"startup": startup, "shutdown": shutdown}


def main():
    print("[*] Analyzing Python code in brain_py/ ...")
    py_results = analyze_python_imports_and_calls(PROJECT_ROOT / "brain_py")

    print("[*] Analyzing Go code in core_go/ ...")
    go_results = analyze_go_imports_and_calls(PROJECT_ROOT / "core_go")

    print(f"[+] Python files: {len(py_results['files'])}")
    print(f"[+] Python entry points: {py_results['entry_points']}")
    print(f"[+] Go files: {len(go_results['files'])}")
    print(f"[+] Go entry points: {go_results['entry_points']}")

    # Save raw analysis
    raw_output = PROJECT_ROOT / "_data" / "ast_analysis_output.json"
    raw_output.parent.mkdir(exist_ok=True)
    with open(raw_output, "w", encoding="utf-8") as f:
        json.dump({
            "python": py_results,
            "go": go_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"[+] Raw AST analysis saved to {raw_output}")

    # Generate summary
    summary = {
        "project": "Binance HFT System",
        "analysis_date": "2026-04-15",
        "python": {
            "file_count": len(py_results["files"]),
            "entry_points": py_results["entry_points"],
            "top_classes": {},
            "top_functions": {},
        },
        "go": {
            "file_count": len(go_results["files"]),
            "entry_points": go_results["entry_points"],
            "top_structs": {},
            "top_interfaces": {},
        },
        "core_interfaces": find_core_interfaces(py_results, go_results),
        "startup_shutdown": extract_startup_shutdown(py_results, go_results),
        "critical_call_chains": [
            {
                "name": "下单主链路",
                "chain": [
                    "mvp_trader_live.py:run_live_trading()",
                    "-> StrategyBridge.predict()",
                    "-> ExecutionBridge.evaluate_and_reprice()",
                    "-> SHMClient.write_action()",
                    "-> Go engine: engine.go:decisionLoop()",
                    "-> MarginExecutor.PlaceOrder() / OrderExecutor.PlaceOrder()",
                    "-> Binance REST API POST /api/v3/order",
                    "-> UserDataStream -> OrderFSM.Transition()",
                    "-> Event ring buffer -> Python EventSHMClient.consume_events()",
                ]
            },
            {
                "name": "市场数据链路",
                "chain": [
                    "Binance WebSocket (depth + trade + ticker)",
                    "-> websocket_manager.go / reconnectable_ws.go",
                    "-> shm_manager.go writes MarketState to mmap",
                    "-> Python SHMClient.read_state()",
                ]
            },
            {
                "name": "风控链路",
                "chain": [
                    "pnl_watchdog.py monitors logs & Go /api/v1/status",
                    "-> On kill_switch triggered: writes .emergency_stop_marker",
                    "-> stop_hft_margin.bat kills all PIDs",
                ]
            },
        ],
    }

    # Top classes/functions by count
    for k, v in sorted(py_results["classes"].items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        summary["python"]["top_classes"][k] = v
    for k, v in sorted(py_results["functions"].items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        summary["python"]["top_functions"][k] = v
    for k, v in sorted(go_results["structs"].items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        summary["go"]["top_structs"][k] = v
    for k, v in sorted(go_results["interfaces"].items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        summary["go"]["top_interfaces"][k] = v

    summary_output = PROJECT_ROOT / "_data" / "ast_analysis_summary.json"
    with open(summary_output, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[+] Analysis summary saved to {summary_output}")

    # Print human-readable report
    print("\n" + "=" * 70)
    print("CORE INTERFACES")
    print("=" * 70)
    for iface in summary["core_interfaces"]:
        print(f"\n• {iface['name']}")
        print(f"  Location: {iface['location']}")
        print(f"  Input:  {iface['input']}")
        print(f"  Output: {iface['output']}")
        if "endpoints" in iface:
            for ep in iface["endpoints"]:
                print(f"    {ep}")

    print("\n" + "=" * 70)
    print("STARTUP SEQUENCE")
    print("=" * 70)
    for phase in summary["startup_shutdown"]["startup"]["phases"]:
        print(f"  {phase}")

    print("\n" + "=" * 70)
    print("SHUTDOWN SEQUENCE")
    print("=" * 70)
    for step in summary["startup_shutdown"]["shutdown"]["steps"]:
        print(f"  {step}")

    print("\n" + "=" * 70)
    print("CRITICAL CALL CHAINS")
    print("=" * 70)
    for chain in summary["critical_call_chains"]:
        print(f"\n  [{chain['name']}]")
        for step in chain["chain"]:
            print(f"    {step}")

    print("\n" + "=" * 70)
    print("TOP GO STRUCTS")
    print("=" * 70)
    for path, structs in list(summary["go"]["top_structs"].items())[:10]:
        print(f"  {path}: {', '.join(structs)}")

    print("\n" + "=" * 70)
    print("TOP PYTHON CLASSES")
    print("=" * 70)
    for path, classes in list(summary["python"]["top_classes"].items())[:10]:
        print(f"  {path}: {', '.join(classes)}")


if __name__ == "__main__":
    main()
