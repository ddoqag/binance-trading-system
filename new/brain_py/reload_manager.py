"""
reload_manager.py - 跨平台策略热重载管理器

提供 HTTP API 和命令行接口用于热重载策略，
绕过 Windows 模块导入的限制。

使用方法:
    # 启动管理服务器
    python reload_manager.py --serve --port 8080

    # 命令行触发重载
    python reload_manager.py --reload strategy_name

    # Python API
    from reload_manager import ReloadManager
    manager = ReloadManager(registry)
    manager.reload_strategy('strategy_name')
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any

# 添加 brain_py 到路径
sys.path.insert(0, str(Path(__file__).parent))

from agent_registry import AgentRegistry, get_global_registry


class ReloadManager:
    """策略热重载管理器"""

    def __init__(self, registry: Optional[AgentRegistry] = None):
        self.registry = registry or get_global_registry()
        self._reload_history: list = []

    def reload_strategy(self, name: str, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        热重载策略

        Args:
            name: 策略名称
            file_path: 可选的新文件路径（如果不提供，使用原文件路径）

        Returns:
            重载结果字典
        """
        result = {
            'success': False,
            'strategy': name,
            'timestamp': time.time(),
            'message': '',
            'old_version': None,
            'new_version': None
        }

        try:
            # 获取当前策略信息
            agent = self.registry.get(name)
            if agent is None:
                result['message'] = f"Strategy '{name}' not found"
                return result

            result['old_version'] = getattr(agent, 'VERSION', 'unknown')

            # 使用提供的文件路径或原路径
            if file_path is None:
                info = self.registry.get_info(name)
                if info and info.metadata.config:
                    file_path = info.metadata.config.get('_source_file')

            if not file_path or not os.path.exists(file_path):
                result['message'] = f"Source file not found for strategy '{name}'"
                return result

            # 执行热重载
            success = self.registry.hot_reload(name)

            if success:
                new_agent = self.registry.get(name)
                result['new_version'] = getattr(new_agent, 'VERSION', 'unknown')
                result['success'] = True
                result['message'] = f"Strategy '{name}' reloaded successfully"

                self._reload_history.append({
                    'strategy': name,
                    'timestamp': time.time(),
                    'old_version': result['old_version'],
                    'new_version': result['new_version']
                })
            else:
                result['message'] = f"Hot reload failed for strategy '{name}'"

        except Exception as e:
            result['message'] = f"Error: {str(e)}"
            import traceback
            result['traceback'] = traceback.format_exc()

        return result

    def reload_all(self) -> list:
        """重载所有策略"""
        results = []
        for name in self.registry.list_agents():
            result = self.reload_strategy(name)
            results.append(result)
        return results

    def get_reload_history(self) -> list:
        """获取重载历史"""
        return self._reload_history.copy()

    def watch_and_reload(self, directory: str, interval: float = 1.0):
        """
        监视目录并自动重载变化的策略

        Args:
            directory: 要监视的目录
            interval: 检查间隔（秒）
        """
        import hashlib

        file_hashes: Dict[str, str] = {}

        print(f"Watching directory: {directory}")
        print(f"Press Ctrl+C to stop")

        try:
            while True:
                for filename in os.listdir(directory):
                    if filename.endswith('.py'):
                        filepath = os.path.join(directory, filename)

                        # 计算文件哈希
                        with open(filepath, 'rb') as f:
                            file_hash = hashlib.md5(f.read()).hexdigest()

                        # 检查是否变化
                        if filepath in file_hashes:
                            if file_hashes[filepath] != file_hash:
                                print(f"File changed: {filename}")

                                # 查找对应的策略
                                for name in self.registry.list_agents():
                                    info = self.registry.get_info(name)
                                    if info and info.metadata.config:
                                        src_file = info.metadata.config.get('_source_file')
                                        if src_file == filepath:
                                            result = self.reload_strategy(name)
                                            print(f"  Reload: {result['message']}")

                        file_hashes[filepath] = file_hash

                time.sleep(interval)

        except KeyboardInterrupt:
            print("\nStopped watching")


def main():
    parser = argparse.ArgumentParser(description='Strategy Hot Reload Manager')
    parser.add_argument('--reload', '-r', metavar='NAME',
                        help='Reload specific strategy by name')
    parser.add_argument('--reload-all', '-a', action='store_true',
                        help='Reload all strategies')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List all registered strategies')
    parser.add_argument('--watch', '-w', metavar='DIR',
                        help='Watch directory for changes and auto-reload')
    parser.add_argument('--serve', '-s', action='store_true',
                        help='Start HTTP server for remote reload')
    parser.add_argument('--port', '-p', type=int, default=8080,
                        help='HTTP server port (default: 8080)')
    parser.add_argument('--file', '-f', metavar='PATH',
                        help='Specify new file path for reload')

    args = parser.parse_args()

    manager = ReloadManager()

    if args.reload:
        # 重载单个策略
        result = manager.reload_strategy(args.reload, args.file)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result['success'] else 1)

    elif args.reload_all:
        # 重载所有策略
        results = manager.reload_all()
        for result in results:
            print(f"{result['strategy']}: {'✓' if result['success'] else '✗'} {result['message']}")
        sys.exit(0)

    elif args.list:
        # 列出策略
        registry = get_global_registry()
        print("Registered Strategies:")
        for name in registry.list_agents():
            agent = registry.get(name)
            version = getattr(agent, 'VERSION', 'unknown')
            print(f"  - {name} (v{version})")

    elif args.watch:
        # 监视模式
        manager.watch_and_reload(args.watch)

    elif args.serve:
        # HTTP 服务器模式
        try:
            from http.server import HTTPServer, BaseHTTPRequestHandler
            import urllib.parse

            class ReloadHandler(BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    # 简化日志
                    pass

                def do_GET(self):
                    parsed = urllib.parse.urlparse(self.path)
                    path = parsed.path

                    if path.startswith('/reload/'):
                        # /reload/strategy_name
                        strategy_name = path.split('/')[-1]
                        result = manager.reload_strategy(strategy_name)

                        self.send_response(200 if result['success'] else 500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(result).encode())

                    elif path == '/list':
                        # 列出所有策略
                        registry = get_global_registry()
                        strategies = []
                        for name in registry.list_agents():
                            agent = registry.get(name)
                            strategies.append({
                                'name': name,
                                'version': getattr(agent, 'VERSION', 'unknown')
                            })

                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'strategies': strategies}).encode())

                    elif path == '/history':
                        # 重载历史
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'history': manager.get_reload_history()
                        }).encode())

                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b'Not Found')

                def do_POST(self):
                    if self.path == '/reload':
                        content_length = int(self.headers.get('Content-Length', 0))
                        post_data = self.rfile.read(content_length)

                        try:
                            data = json.loads(post_data)
                            strategy_name = data.get('strategy')
                            file_path = data.get('file')

                            if strategy_name:
                                result = manager.reload_strategy(strategy_name, file_path)
                                self.send_response(200 if result['success'] else 500)
                                self.send_header('Content-Type', 'application/json')
                                self.end_headers()
                                self.wfile.write(json.dumps(result).encode())
                            else:
                                self.send_response(400)
                                self.end_headers()
                                self.wfile.write(b'Missing strategy name')
                        except json.JSONDecodeError:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b'Invalid JSON')
                    else:
                        self.send_response(404)
                        self.end_headers()

            server = HTTPServer(('0.0.0.0', args.port), ReloadHandler)
            print(f"Reload server started on http://localhost:{args.port}")
            print(f"API endpoints:")
            print(f"  GET  /list              - List all strategies")
            print(f"  GET  /reload/<name>     - Reload specific strategy")
            print(f"  GET  /history           - Get reload history")
            print(f"  POST /reload            - Reload with JSON body: {{'strategy': 'name'}}")
            print(f"\nPress Ctrl+C to stop")

            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nShutting down server...")
                server.shutdown()

        except ImportError as e:
            print(f"Error: {e}")
            print("HTTP server requires Python standard library")
            sys.exit(1)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
