# -*- coding: utf-8 -*-
"""
orchestrator_with_alerts.py - 带告警的完整 Orchestrator 示例

Production-ready 示例，包含：
- 实时异常告警（钉钉/飞书/Telegram）
- 性能监控
- 优雅关闭
- 完整的错误处理和恢复机制

Author: P10 Trading System
"""

import asyncio
import logging
import signal
import sys
import os
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from brain_py.regime_detector import MarketRegimeDetector, RegimePrediction
from core.alert_notifier import AlertNotifier, AlertLevel


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/orchestrator.log')
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class MarketTick:
    """市场数据 Tick"""
    timestamp: float
    price: float
    volume: float
    symbol: str = "BTCUSDT"


class MockDataFeed:
    """模拟数据源（实际使用时替换为 WebSocket/MMAP）"""
    
    def __init__(self):
        self.price = 50000.0
        self._running = True
        
    async def get_next_tick(self) -> Optional[MarketTick]:
        """模拟接收下一个 tick"""
        if not self._running:
            return None
            
        await asyncio.sleep(0.01)  # 模拟 10ms 延迟
        
        # 模拟价格随机游走
        self.price *= (1 + np.random.randn() * 0.001)
        
        return MarketTick(
            timestamp=asyncio.get_event_loop().time(),
            price=self.price,
            volume=np.random.rand() * 10
        )
    
    async def fetch_historical_data(self, n_bars: int) -> np.ndarray:
        """获取历史数据用于训练"""
        returns = np.random.randn(n_bars) * 0.001
        prices = 50000 * np.exp(np.cumsum(returns))
        return prices
    
    def stop(self):
        self._running = False


class ProductionOrchestrator:
    """
    生产级交易编排器
    
    特性：
    - 完整异常捕获和告警
    - 性能监控和自动告警
    - 优雅关闭和资源清理
    - 支持多种通知渠道
    """
    
    def __init__(self):
        # 核心组件
        self.detector = MarketRegimeDetector(
            n_states=3,
            feature_window=100,
            fit_interval_ticks=1000
        )
        self.data_feed = MockDataFeed()
        
        # 告警通知器
        self.notifier = AlertNotifier(
            # 配置你的告警渠道（至少一个）
            # dingtalk_webhook="https://oapi.dingtalk.com/robot/send?access_token=xxx",
            # telegram_bot_token="xxx",
            # telegram_chat_id="xxx",
            min_level=AlertLevel.WARNING,
            rate_limit_seconds=60.0  # 同类告警限流 60 秒
        )
        
        # 状态
        self.is_running = False
        self.tick_count = 0
        self.error_count = 0
        self.max_errors = 10  # 连续错误超过 10 次停止
        
        # 性能监控
        self.latency_buffer = []
        self.latency_threshold = 2.0  # 2ms 告警阈值
        
        # 统计
        self.start_time = None
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """处理系统信号"""
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(self.stop())
    
    async def start(self):
        """启动 Orchestrator"""
        logger.info("=" * 60)
        logger.info("Production Orchestrator Starting")
        logger.info("=" * 60)
        
        self.start_time = datetime.now()
        
        # 1. 冷启动
        try:
            logger.info("[Phase 1/3] Cold start: training initial model...")
            initial_data = await self.data_feed.fetch_historical_data(200)
            success = self.detector.fit(initial_data)
            
            if not success:
                raise RuntimeError("Cold start failed")
            
            logger.info(f"[OK] Cold start complete, model ready: {self.detector._model_ready}")
            
            # 发送启动通知
            await self.notifier.send_alert(
                level=AlertLevel.INFO,
                title="交易系统启动",
                message=f"Orchestrator 已启动，模型类型: {'HMM' if not self.detector._use_fallback else 'Fallback'}",
                metadata={
                    "start_time": self.start_time.isoformat(),
                    "model_ready": self.detector._model_ready
                }
            )
            
        except Exception as e:
            await self.notifier.send_alert(
                level=AlertLevel.CRITICAL,
                title="冷启动失败",
                message=str(e)
            )
            raise
        
        # 2. 启动主循环
        logger.info("[Phase 2/3] Starting main loop...")
        self.is_running = True
        
        try:
            await self.main_trading_loop()
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            await self.notifier.send_alert(
                level=AlertLevel.CRITICAL,
                title="主循环异常退出",
                message=str(e)
            )
        finally:
            await self.stop()
    
    async def main_trading_loop(self):
        """主交易循环"""
        logger.info("[Loop] Main trading loop started")
        
        # 预热
        logger.info("Warming up...")
        for _ in range(100):
            await self.detector.detect_async(50000 + np.random.randn())
        
        logger.info("Warmup complete, entering main loop")
        
        while self.is_running:
            try:
                # 获取市场数据
                tick = await self.data_feed.get_next_tick()
                if tick is None:
                    break
                
                self.tick_count += 1
                
                # Regime 检测
                t0 = asyncio.get_event_loop().time()
                regime = await self.detector.detect_async(tick.price)
                t1 = asyncio.get_event_loop().time()
                
                latency_ms = (t1 - t0) * 1000
                self.latency_buffer.append(latency_ms)
                
                # 延迟告警
                if latency_ms > self.latency_threshold:
                    await self.notifier.send_alert(
                        level=AlertLevel.WARNING,
                        title="检测延迟过高",
                        message=f"当前延迟 {latency_ms:.2f}ms 超过阈值 {self.latency_threshold}ms",
                        metadata={
                            "latency_ms": latency_ms,
                            "tick_count": self.tick_count,
                            "regime": regime.regime.value
                        }
                    )
                
                # 模型更新失败告警
                if not self.detector._model_ready and self.tick_count > 1000:
                    await self.notifier.send_alert(
                        level=AlertLevel.ERROR,
                        title="模型未就绪",
                        message="运行超过 1000 ticks 但模型仍未就绪",
                        metadata={"tick_count": self.tick_count}
                    )
                
                # 定期报告
                if self.tick_count % 1000 == 0:
                    await self._send_status_report()
                
                # 错误计数重置
                self.error_count = 0
                
            except asyncio.CancelledError:
                logger.info("Loop cancelled")
                break
            except Exception as e:
                self.error_count += 1
                logger.error(f"Tick processing error: {e}")
                
                # 连续错误告警
                if self.error_count >= self.max_errors:
                    await self.notifier.send_alert(
                        level=AlertLevel.CRITICAL,
                        title="连续错误超限",
                        message=f"连续 {self.error_count} 次错误，系统即将停止",
                        metadata={"error": str(e)}
                    )
                    break
                
                await asyncio.sleep(0.1)
    
    async def _send_status_report(self):
        """发送状态报告"""
        if not self.latency_buffer:
            return
        
        recent = self.latency_buffer[-1000:]
        avg_latency = np.mean(recent)
        p99_latency = np.percentile(recent, 99)
        
        uptime = (datetime.now() - self.start_time).total_seconds()
        
        logger.info(
            f"Status Report | Ticks: {self.tick_count} | "
            f"Avg Latency: {avg_latency:.3f}ms | P99: {p99_latency:.3f}ms | "
            f"Uptime: {uptime/3600:.1f}h"
        )
        
        # 发送 INFO 级别通知（频率较低）
        await self.notifier.send_alert(
            level=AlertLevel.INFO,
            title="系统状态报告",
            message=f"运行正常，已处理 {self.tick_count} ticks",
            metadata={
                "avg_latency_ms": avg_latency,
                "p99_latency_ms": p99_latency,
                "uptime_hours": uptime / 3600,
                "model_ready": self.detector._model_ready
            }
        )
    
    async def stop(self):
        """优雅关闭"""
        if not self.is_running:
            return
        
        logger.info("[Phase 3/3] Graceful shutdown...")
        self.is_running = False
        
        try:
            # 停止数据 feed
            self.data_feed.stop()
            
            # 关闭 detector
            self.detector.shutdown()
            
            # 关闭 notifier
            await self.notifier.close()
            
            # 发送关闭通知
            uptime = (datetime.now() - self.start_time).total_seconds()
            await self.notifier.send_alert(
                level=AlertLevel.INFO,
                title="交易系统关闭",
                message=f"系统已正常关闭，运行时间 {uptime/3600:.2f} 小时",
                metadata={
                    "total_ticks": self.tick_count,
                    "uptime_seconds": uptime
                }
            )
            
            logger.info("[OK] Shutdown complete")
            
        except Exception as e:
            logger.error(f"Shutdown error: {e}")
            await self.notifier.send_alert(
                level=AlertLevel.ERROR,
                title="关闭异常",
                message=str(e)
            )


async def main():
    """入口函数"""
    orchestrator = ProductionOrchestrator()
    
    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        await orchestrator.stop()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # 创建日志目录
    os.makedirs("logs", exist_ok=True)
    
    # 运行
    asyncio.run(main())
