"""
仪表板服务器
提供Web界面和API端点
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
from urllib.parse import parse_qs, urlparse

from .metrics_collector import MetricsCollector

logger = logging.getLogger(__name__)


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP请求处理器"""

    def log_message(self, format, *args):
        """禁用默认日志"""
        pass

    def do_GET(self):
        """处理GET请求"""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # API端点
        if path == '/api/metrics':
            self._send_json(self.server.get_metrics())
        elif path == '/api/stats':
            self._send_json(self.server.get_stats())
        elif path == '/api/equity':
            self._send_json(self.server.get_equity_curve())
        elif path == '/api/trades':
            limit = int(query.get('limit', [10])[0])
            self._send_json(self.server.get_recent_trades(limit))
        elif path == '/api/prometheus':
            self._send_prometheus(self.server.get_prometheus_metrics())
        elif path == '/health':
            self._send_json({'status': 'healthy'})

        # 静态页面
        elif path == '/' or path == '/dashboard':
            self._send_html(self._get_dashboard_html())
        elif path == '/simple':
            self._send_html(self._get_simple_html())

        else:
            self._send_error(404, 'Not found')

    def _send_json(self, data: Dict):
        """发送JSON响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _send_prometheus(self, text: str):
        """发送Prometheus格式响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(text.encode())

    def _send_html(self, html: str):
        """发送HTML响应"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def _send_error(self, code: int, message: str):
        """发送错误响应"""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'error': message}).encode())

    def _get_dashboard_html(self) -> str:
        """获取仪表板HTML"""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Trading System Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f1419;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            text-align: center;
            padding: 20px;
            border-bottom: 1px solid #2a3441;
            margin-bottom: 20px;
        }
        .header h1 { color: #00d4aa; font-size: 24px; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .card {
            background: #1a2332;
            border-radius: 8px;
            padding: 20px;
            border: 1px solid #2a3441;
        }
        .card h3 {
            color: #8899a6;
            font-size: 12px;
            text-transform: uppercase;
            margin-bottom: 10px;
        }
        .card .value {
            font-size: 28px;
            font-weight: bold;
            color: #fff;
        }
        .card .value.positive { color: #00d4aa; }
        .card .value.negative { color: #ff6b6b; }
        .card .subtitle {
            font-size: 12px;
            color: #8899a6;
            margin-top: 5px;
        }
        .section {
            background: #1a2332;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            border: 1px solid #2a3441;
        }
        .section h2 {
            color: #fff;
            font-size: 16px;
            margin-bottom: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            text-align: left;
            padding: 10px;
            border-bottom: 1px solid #2a3441;
        }
        th {
            color: #8899a6;
            font-weight: normal;
            font-size: 12px;
        }
        .status {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
        }
        .status.active { background: #00d4aa20; color: #00d4aa; }
        .status.warning { background: #ffa50020; color: #ffa500; }
        .status.danger { background: #ff6b6b20; color: #ff6b6b; }
        .refresh-info {
            text-align: center;
            color: #8899a6;
            font-size: 12px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Self-Evolving Trading System</h1>
        <p>Real-time Trading Dashboard</p>
    </div>

    <div class="grid" id="metrics">
        <div class="card">
            <h3>Total Equity</h3>
            <div class="value" id="equity">$--</div>
            <div class="subtitle">Available + Positions</div>
        </div>
        <div class="card">
            <h3>Daily P&L</h3>
            <div class="value" id="daily-pnl">$--</div>
            <div class="subtitle">Today\'s profit/loss</div>
        </div>
        <div class="card">
            <h3>Win Rate</h3>
            <div class="value" id="win-rate">--%</div>
            <div class="subtitle">Overall trade success</div>
        </div>
        <div class="card">
            <h3>Active Strategies</h3>
            <div class="value" id="strategies">--</div>
            <div class="subtitle">Currently running</div>
        </div>
    </div>

    <div class="section">
        <h2>System Status</h2>
        <table>
            <tr>
                <th>Component</th>
                <th>Status</th>
                <th>Details</th>
            </tr>
            <tr>
                <td>Trading Engine</td>
                <td><span class="status active">Active</span></td>
                <td id="engine-status">Running</td>
            </tr>
            <tr>
                <td>Risk Manager</td>
                <td><span class="status active">Normal</span></td>
                <td id="risk-status">Within limits</td>
            </tr>
            <tr>
                <td>Data Feed</td>
                <td><span class="status active">Connected</span></td>
                <td id="data-status">Live</td>
            </tr>
        </table>
    </div>

    <div class="section">
        <h2>Recent Trades</h2>
        <table id="trades-table">
            <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Quantity</th>
                <th>Price</th>
                <th>P&L</th>
            </tr>
        </table>
    </div>

    <div class="refresh-info">
        Auto-refresh every 5 seconds | <a href="/api/metrics" style="color: #00d4aa;">API</a>
    </div>

    <script>
        async function fetchMetrics() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();

                if (data.current_metrics) {
                    const m = data.current_metrics;
                    document.getElementById('equity').textContent = '$' + m.total_equity.toLocaleString();
                    document.getElementById('daily-pnl').textContent = '$' + m.daily_pnl.toLocaleString();
                    document.getElementById('daily-pnl').className = 'value ' + (m.daily_pnl >= 0 ? 'positive' : 'negative');
                    document.getElementById('win-rate').textContent = (m.win_rate * 100).toFixed(1) + '%';
                    document.getElementById('strategies').textContent = m.active_strategies;
                }
            } catch (e) {
                console.error('Failed to fetch metrics:', e);
            }
        }

        async function fetchTrades() {
            try {
                const response = await fetch('/api/trades?limit=5');
                const trades = await response.json();

                const table = document.getElementById('trades-table');
                table.innerHTML = `
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>P&L</th>
                    </tr>
                `;

                trades.forEach(trade => {
                    const row = table.insertRow();
                    row.innerHTML = `
                        <td>${new Date(trade.timestamp * 1000).toLocaleTimeString()}</td>
                        <td>${trade.symbol}</td>
                        <td style="color: ${trade.side === 'buy' ? '#00d4aa' : '#ff6b6b'}">${trade.side.toUpperCase()}</td>
                        <td>${trade.quantity.toFixed(4)}</td>
                        <td>$${trade.price.toFixed(2)}</td>
                        <td style="color: ${trade.pnl >= 0 ? '#00d4aa' : '#ff6b6b'}">${trade.pnl ? '$' + trade.pnl.toFixed(2) : '-'}</td>
                    `;
                });
            } catch (e) {
                console.error('Failed to fetch trades:', e);
            }
        }

        // Initial load
        fetchMetrics();
        fetchTrades();

        // Auto-refresh
        setInterval(fetchMetrics, 5000);
        setInterval(fetchTrades, 5000);
    </script>
</body>
</html>'''

    def _get_simple_html(self) -> str:
        """获取简化版HTML"""
        return '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Trading Status</title>
    <style>
        body { font-family: monospace; background: #000; color: #0f0; padding: 20px; }
        .metric { margin: 10px 0; }
        .label { color: #888; }
    </style>
</head>
<body>
    <h1>Trading System Status</h1>
    <div id="status">Loading...</div>
    <script>
        async function update() {
            const res = await fetch('/api/stats');
            const data = await res.json();
            document.getElementById('status').innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
        }
        update();
        setInterval(update, 5000);
    </script>
</body>
</html>'''


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程HTTP服务器"""
    allow_reuse_address = True
    daemon_threads = True


class DashboardServer:
    """
    仪表板服务器

    提供:
    - Web界面 (/dashboard)
    - API端点 (/api/*)
    - Prometheus指标 (/api/prometheus)
    """

    def __init__(
        self,
        metrics_collector: Optional[MetricsCollector] = None,
        host: str = "0.0.0.0",
        port: int = 8080
    ):
        self.metrics_collector = metrics_collector or MetricsCollector()
        self.host = host
        self.port = port
        self._server: Optional[ThreadedHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

        logger.info(f"[DashboardServer] Initialized on {host}:{port}")

    def start(self):
        """启动服务器"""
        if self._running:
            return

        self._server = ThreadedHTTPServer((self.host, self.port), DashboardHandler)
        self._server.metrics_collector = self.metrics_collector

        # 绑定方法
        self._server.get_metrics = self.get_metrics
        self._server.get_stats = self.get_stats
        self._server.get_equity_curve = self.get_equity_curve
        self._server.get_recent_trades = self.get_recent_trades
        self._server.get_prometheus_metrics = self.get_prometheus_metrics

        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.daemon = True
        self._thread.start()

        self._running = True
        logger.info(f"[DashboardServer] Started on http://{self.host}:{self.port}")

    def stop(self):
        """停止服务器"""
        if not self._running:
            return

        if self._server:
            self._server.shutdown()
            self._server.server_close()

        self._running = False
        logger.info("[DashboardServer] Stopped")

    # ==================== API方法 ====================

    def get_metrics(self) -> Dict:
        """获取当前指标"""
        if self.metrics_collector.current_metrics:
            m = self.metrics_collector.current_metrics
            return {
                'total_equity': m.total_equity,
                'cash': m.cash,
                'positions_value': m.positions_value,
                'daily_pnl': m.daily_pnl,
                'total_pnl': m.total_pnl,
                'win_rate': m.win_rate,
                'drawdown': m.current_drawdown,
                'risk_score': m.risk_score,
                'active_strategies': m.active_strategies
            }
        return {}

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.metrics_collector.get_current_stats()

    def get_equity_curve(self) -> list:
        """获取权益曲线"""
        return self.metrics_collector.get_equity_curve()

    def get_recent_trades(self, limit: int = 10) -> list:
        """获取最近交易"""
        return self.metrics_collector.get_recent_trades(limit)

    def get_prometheus_metrics(self) -> str:
        """获取Prometheus格式指标"""
        return self.metrics_collector.get_prometheus_metrics()

    def is_running(self) -> bool:
        """检查服务器是否运行"""
        return self._running
