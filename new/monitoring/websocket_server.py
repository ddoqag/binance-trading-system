"""
WebSocket服务器
实时推送交易数据到前端
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Callable, Any
from dataclasses import asdict
import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    WebSocket服务器

    提供实时数据推送:
    - 权益曲线更新
    - 交易通知
    - 风险警报
    - 策略状态
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.clients: Set[WebSocketServerProtocol] = set()
        self._running = False
        self._server = None

        # 消息处理器
        self._handlers: Dict[str, Callable] = {}

        logger.info(f"[WebSocketServer] Initialized on {host}:{port}")

    async def start(self):
        """启动WebSocket服务器"""
        if self._running:
            return

        self._running = True

        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=10
        )

        logger.info(f"[WebSocketServer] Started on ws://{self.host}:{self.port}")

    async def stop(self):
        """停止WebSocket服务器"""
        self._running = False

        # 关闭所有客户端连接
        if self.clients:
            await asyncio.gather(
                *[client.close() for client in self.clients],
                return_exceptions=True
            )
            self.clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        logger.info("[WebSocketServer] Stopped")

    async def _handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """处理客户端连接"""
        self.clients.add(websocket)
        client_info = f"{websocket.remote_address}"
        logger.info(f"[WebSocketServer] Client connected: {client_info}")

        try:
            # 发送欢迎消息
            await self._send_to_client(websocket, {
                'type': 'connected',
                'message': 'Welcome to Trading System WebSocket'
            })

            # 处理客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(websocket, data)
                except json.JSONDecodeError:
                    await self._send_to_client(websocket, {
                        'type': 'error',
                        'message': 'Invalid JSON'
                    })
                except Exception as e:
                    logger.error(f"[WebSocketServer] Message handling error: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"[WebSocketServer] Client disconnected: {client_info}")
        finally:
            self.clients.discard(websocket)

    async def _handle_message(self, client: WebSocketServerProtocol, data: Dict):
        """处理客户端消息"""
        msg_type = data.get('type')

        if msg_type == 'subscribe':
            channel = data.get('channel', 'all')
            await self._send_to_client(client, {
                'type': 'subscribed',
                'channel': channel
            })

        elif msg_type == 'ping':
            await self._send_to_client(client, {'type': 'pong'})

        elif msg_type in self._handlers:
            handler = self._handlers[msg_type]
            result = handler(data)
            if asyncio.iscoroutine(result):
                result = await result
            await self._send_to_client(client, {
                'type': f'{msg_type}_response',
                'data': result
            })

        else:
            await self._send_to_client(client, {
                'type': 'error',
                'message': f'Unknown message type: {msg_type}'
            })

    async def _send_to_client(self, client: WebSocketServerProtocol, data: Dict):
        """发送消息给指定客户端"""
        try:
            await client.send(json.dumps(data, default=str))
        except Exception as e:
            logger.error(f"[WebSocketServer] Send error: {e}")
            self.clients.discard(client)

    async def broadcast(self, data: Dict):
        """
        广播消息给所有客户端

        Args:
            data: 要发送的数据
        """
        if not self.clients:
            return

        message = json.dumps(data, default=str)

        # 发送给所有客户端
        disconnected = set()
        for client in self.clients:
            try:
                await client.send(message)
            except Exception as e:
                logger.error(f"[WebSocketServer] Broadcast error: {e}")
                disconnected.add(client)

        # 清理断开的客户端
        self.clients -= disconnected

    # ==================== 便捷推送方法 ====================

    async def push_equity_update(self, equity: float, cash: float, positions_value: float):
        """推送权益更新"""
        await self.broadcast({
            'type': 'equity_update',
            'timestamp': asyncio.get_event_loop().time(),
            'data': {
                'equity': equity,
                'cash': cash,
                'positions_value': positions_value
            }
        })

    async def push_trade(self, symbol: str, side: str, quantity: float,
                         price: float, pnl: float = 0.0):
        """推送交易通知"""
        await self.broadcast({
            'type': 'trade',
            'timestamp': asyncio.get_event_loop().time(),
            'data': {
                'symbol': symbol,
                'side': side,
                'quantity': quantity,
                'price': price,
                'pnl': pnl
            }
        })

    async def push_risk_alert(self, level: str, message: str, metrics: Dict):
        """推送风险警报"""
        await self.broadcast({
            'type': 'risk_alert',
            'timestamp': asyncio.get_event_loop().time(),
            'data': {
                'level': level,
                'message': message,
                'metrics': metrics
            }
        })

    async def push_strategy_update(self, strategies: Dict[str, Any]):
        """推送策略状态更新"""
        await self.broadcast({
            'type': 'strategy_update',
            'timestamp': asyncio.get_event_loop().time(),
            'data': strategies
        })

    def register_handler(self, msg_type: str, handler: Callable):
        """注册消息处理器"""
        self._handlers[msg_type] = handler

    def get_client_count(self) -> int:
        """获取连接客户端数量"""
        return len(self.clients)
