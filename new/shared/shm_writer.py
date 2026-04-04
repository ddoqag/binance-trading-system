"""
shm_writer.py
Python 端共享内存写入器
写入 AI 决策（订单命令）到共享内存供 Go Engine 读取
"""

import mmap
import struct
import time
from typing import Optional
from .protocol import (
    MessageType, OrderCommand, ORDER_COMMAND_SIZE,
    HFT_SHM_SIZE_DEFAULT, HFT_PROTOCOL_MAGIC, HFT_PROTOCOL_VERSION,
    AIContext, pack_ai_context, AI_CONTEXT_OFFSET, AI_CONTEXT_SIZE,
)


class SharedMemoryOrderWriter:
    """共享内存订单命令写入器

    将 Python AI 引擎生成的订单命令写入共享内存
    Go Engine 从这里读取并执行
    """

    def __init__(self, shm_name: str = "hft_shared_memory", size: int = HFT_SHM_SIZE_DEFAULT):
        self.shm_name = shm_name
        self.size = size
        self.mmap: Optional[mmap.mmap] = None
        self._command_id_counter = 0
        self._write_pos = 0

    def connect(self) -> bool:
        """连接到共享内存（写入模式）"""
        try:
            # 在 Windows 上，需要先存在一个文件映射
            self.mmap = mmap.mmap(
                -1,
                self.size,
                tagname=self.shm_name,
                access=mmap.ACCESS_WRITE
            )

            # 验证头部
            self.mmap.seek(0)
            magic = struct.unpack('<I', self.mmap.read(4))[0]
            if magic != HFT_PROTOCOL_MAGIC:
                print(f"[ERROR] Invalid magic in shared memory: 0x{magic:08x}")
                return False

            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to shared memory: {e}")
            return False

    def _next_command_id(self) -> int:
        """获取下一个命令ID"""
        self._command_id_counter += 1
        return self._command_id_counter

    def pack_order_command(self, command: OrderCommand) -> bytes:
        """打包订单命令为二进制"""
        return struct.pack(
            '<QQIIdddB',
            command.command_id,
            command.timestamp_ns,
            command.order_type,
            command.side,
            command.price,
            command.quantity,
            command.max_slippage_bps,
            command.expires_after_ms,
            1 if command.dry_run else 0
        )

    def write_limit_order(self, side: int, price: float, quantity: float,
                          expires_after_ms: int = 5000,
                          max_slippage_bps: float = 10.0,
                          dry_run: bool = True) -> int:
        """写入限价单命令

        Args:
            side: OrderSide.BUY 或 OrderSide.SELL
            price: 限价价格
            quantity: 数量
            expires_after_ms: 过期时间（毫秒）
            max_slippage_bps: 最大滑点（基点）
            dry_run: 是否模拟执行

        Returns:
            命令ID，-1 表示失败
        """
        if self.mmap is None:
            return -1

        command_id = self._next_command_id()
        command = OrderCommand(
            command_id=command_id,
            timestamp_ns=time.time_ns(),
            order_type=2,  # ORDER_TYPE_LIMIT
            side=side,
            price=price,
            quantity=quantity,
            max_slippage_bps=max_slippage_bps,
            expires_after_ms=expires_after_ms,
            dry_run=dry_run
        )

        return self._write_command(MessageType.ORDER_COMMAND, self.pack_order_command(command))

    def write_market_order(self, side: int, quantity: float,
                           max_slippage_bps: float = 10.0,
                           dry_run: bool = True) -> int:
        """写入市价单命令"""
        if self.mmap is None:
            return -1

        command_id = self._next_command_id()
        command = OrderCommand(
            command_id=command_id,
            timestamp_ns=time.time_ns(),
            order_type=1,  # ORDER_TYPE_MARKET
            side=side,
            price=0.0,  # 市价单价格为0
            quantity=quantity,
            max_slippage_bps=max_slippage_bps,
            expires_after_ms=0,
            dry_run=dry_run
        )

        return self._write_command(MessageType.ORDER_COMMAND, self.pack_order_command(command))

    def write_cancel_order(self, order_id: int) -> int:
        """写入撤单命令"""
        if self.mmap is None:
            return -1

        command_id = self._next_command_id()
        command = OrderCommand(
            command_id=command_id,
            timestamp_ns=time.time_ns(),
            order_type=3,  # ORDER_TYPE_CANCEL
            side=0,
            price=float(order_id),  # 将order_id编码在价格字段
            quantity=0.0,
            max_slippage_bps=0.0,
            expires_after_ms=0,
            dry_run=False
        )

        return self._write_command(MessageType.ORDER_COMMAND, self.pack_order_command(command))

    def _write_command(self, msg_type: int, data: bytes) -> int:
        """写入消息到环形缓冲区"""
        # 简化实现：写入到固定的命令区域
        # 完整实现需要处理环形缓冲区和读写索引同步

        # 计算命令区域的偏移量
        # 头部 + 最新快照 + 命令缓冲区
        header_size = struct.calcsize('<I I Q Q Q Q Q Q Q Q Q Q')  # 基础头部
        header_size += struct.calcsize('<I I Q I B B')  # heartbeat
        header_size += struct.calcsize('<d d d d d d I')  # account_info

        # 市场快照：固定大小
        from .protocol import MARKET_SNAPSHOT_SIZE
        snapshot_size = MARKET_SNAPSHOT_SIZE

        command_buffer_offset = header_size + snapshot_size

        # 写入消息头
        self.mmap.seek(command_buffer_offset)
        self.mmap.write(struct.pack('<II', msg_type, len(data)))

        # 写入数据
        self.mmap.write(data)

        # 冲刷到内存
        self.mmap.flush()

        return self._command_id_counter

    def write_ai_context(self, ctx: AIContext) -> bool:
        """写入 AI 决策上下文到固定偏移位置"""
        if self.mmap is None:
            return False
        try:
            self.mmap.seek(AI_CONTEXT_OFFSET)
            self.mmap.write(pack_ai_context(ctx))
            self.mmap.flush()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to write AI context: {e}")
            return False

    def update_ai_heartbeat(self, running: bool = True):
        """更新AI引擎心跳时间戳"""
        if self.mmap is None:
            return

        # last_heartbeat_ai_ns 在头部末尾
        # 偏移: 4 + 4 + 8 + (8 * 6) + 8 + 8 = 4+4+8+48+8+8 = 80
        self.mmap.seek(80)
        self.mmap.write(struct.pack('<Q', time.time_ns()))
        self.mmap.flush()

    def get_last_read_index(self) -> int:
        """获取Go端读取索引"""
        if self.mmap is None:
            return 0
        self.mmap.seek(4 + 4 + 8 + 8)  # magic, version, size -> go_write_index -> go_read_index
        ai_read_index = struct.unpack('<Q', self.mmap.read(8))[0]
        return ai_read_index

    def close(self):
        """关闭共享内存映射"""
        if self.mmap:
            self.mmap.close()
            self.mmap = None
