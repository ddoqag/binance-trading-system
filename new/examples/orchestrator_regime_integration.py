"""
orchestrator_regime_integration.py - Orchestrator 接入示例

展示如何在 asyncio 架构下正确接入异步 Regime Detector：
- 冷启动预热
- 高速推理循环（< 1ms）
- 后台模型更新管理
- 优雅关闭

Author: P10 Trading System
"""

import asyncio
import logging
import numpy as np
from typing import Optional
from dataclasses import dataclass

# 假设的项目结构
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_py.regime_detector import MarketRegimeDetector, RegimePrediction


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
        
    async def get_next_tick(self) -> MarketTick:
        """模拟接收下一个 tick"""
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
        # 模拟随机游走价格序列
        returns = np.random.randn(n_bars) * 0.001
        prices = 50000 * np.exp(np.cumsum(returns))
        return prices


class StrategyAdapter:
    """策略适配器：根据 regime 调整策略参数"""
    
    def __init__(self):
        self.current_regime = "UNKNOWN"
        self.parameters = {
            "position_size": 0.5,
            "stop_loss_pct": 0.02,
            "take_profit_pct": 0.04,
            "aggressiveness": "normal"
        }
    
    def update_regime(self, regime: str):
        """根据市场状态调整策略"""
        if regime == self.current_regime:
            return
        
        self.current_regime = regime
        
        if regime == "TRENDING":
            # 趋势市场：更激进，持仓更久
            self.parameters.update({
                "position_size": 0.8,
                "stop_loss_pct": 0.03,
                "take_profit_pct": 0.08,
                "aggressiveness": "high"
            })
            logger.info("[Strategy] 切换到趋势模式: 激进持仓")
            
        elif regime == "MEAN_REVERTING":
            # 震荡市场：保守，快速止盈止损
            self.parameters.update({
                "position_size": 0.4,
                "stop_loss_pct": 0.015,
                "take_profit_pct": 0.025,
                "aggressiveness": "low"
            })
            logger.info("[Strategy] 切换到震荡模式: 高频套利")
            
        elif regime == "HIGH_VOLATILITY":
            # 高波动：降低仓位，收紧风控
            self.parameters.update({
                "position_size": 0.2,
                "stop_loss_pct": 0.01,
                "take_profit_pct": 0.02,
                "aggressiveness": "very_low"
            })
            logger.info("[Strategy] 切换到高波动模式: 降低风险")


class TradingOrchestrator:
    """
    交易编排器：整合 Regime Detector 的高性能实现
    
    核心设计：
    1. 双轨制：推理循环 + 训练管理独立运行
    2. 延迟敏感：主循环 < 1ms，异常延迟自动告警
    3. 资源管理：优雅关闭，避免僵尸进程
    """
    
    def __init__(self):
        self.detector = MarketRegimeDetector(
            n_states=3,
            feature_window=100,
            fit_interval_ticks=1000  # 每 1000 tick 自动触发
        )
        self.data_feed = MockDataFeed()
        self.strategy = StrategyAdapter()
        self.is_running = False
        
        # 性能监控
        self.latency_buffer = []
        self.tick_count = 0
        
    async def start(self):
        """启动 Orchestrator"""
        logger.info("=" * 60)
        logger.info("Trading Orchestrator 启动")
        logger.info("=" * 60)
        
        # 1. 冷启动：同步预热（重要！）
        logger.info("[Phase 1/3] 冷启动：训练初始模型...")
        initial_data = await self.data_feed.fetch_historical_data(200)
        success = self.detector.fit(initial_data)
        if not success:
            raise RuntimeError("冷启动失败，无法初始化模型")
        logger.info(f"✅ 冷启动完成，模型就绪: {self.detector._model_ready}")
        
        # 2. 启动双轨任务
        logger.info("[Phase 2/3] 启动双轨任务...")
        self.is_running = True
        
        try:
            await asyncio.gather(
                self.main_trading_loop(),
                self.model_update_manager(),
                self.performance_monitor()
            )
        except asyncio.CancelledError:
            logger.info("收到取消信号，正在优雅关闭...")
        finally:
            await self.stop()
    
    async def main_trading_loop(self):
        """
        主交易循环：高速推理路径
        
        关键要求：
        - 延迟 < 1ms
        - 不阻塞（所有重操作异步）
        - 异常捕获完备
        """
        logger.info("[Loop] 主交易循环启动")
        
        while self.is_running:
            try:
                # 获取市场数据
                tick = await self.data_feed.get_next_tick()
                self.tick_count += 1
                
                # 核心：非阻塞 regime 检测
                t0 = asyncio.get_event_loop().time()
                regime = await self.detector.detect_async(tick.price)
                t1 = asyncio.get_event_loop().time()
                
                latency_ms = (t1 - t0) * 1000
                self.latency_buffer.append(latency_ms)
                
                # 延迟告警
                if latency_ms > 1.0:
                    logger.warning(f"[Latency Alert] 高延迟 detected: {latency_ms:.2f}ms")
                
                # 更新策略
                self.strategy.update_regime(regime.regime.value)
                
                # 执行交易逻辑（简化示例）
                await self.execute_strategy(tick, regime)
                
                # 进度报告（每 100 ticks）
                if self.tick_count % 100 == 0:
                    avg_latency = np.mean(self.latency_buffer[-100:])
                    logger.info(f"[Status] Ticks: {self.tick_count}, "
                               f"Avg Latency: {avg_latency:.3f}ms, "
                               f"Regime: {regime.regime.value}")
                
            except Exception as e:
                logger.error(f"[Loop Error] {e}")
                await asyncio.sleep(0.1)  # 错误后短暂休眠
    
    async def model_update_manager(self):
        """
        模型更新管理器：低频率后台任务
        
        注意：这里使用显式的定时更新，与 detector 内部的
        fit_interval_ticks 形成双重保险
        """
        logger.info("[Manager] 模型更新管理器启动")
        
        while self.is_running:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                
                if not self.is_running:
                    break
                
                # 评估是否需要重训练
                if self.should_retrain():
                    logger.info("[Manager] 触发模型重训练...")
                    new_data = await self.data_feed.fetch_historical_data(500)
                    
                    # 异步训练，不等待结果（让它在后台跑）
                    asyncio.create_task(self.detector._async_fit(new_data))
                
            except Exception as e:
                logger.error(f"[Manager Error] {e}")
    
    async def performance_monitor(self):
        """性能监控：定期检查系统健康"""
        while self.is_running:
            await asyncio.sleep(10)  # 每 10 秒报告一次
            
            if len(self.latency_buffer) > 0:
                recent = self.latency_buffer[-1000:]
                p50 = np.median(recent)
                p99 = np.percentile(recent, 99)
                max_lat = np.max(recent)
                
                logger.info(f"[Monitor] Latency p50={p50:.3f}ms, "
                           f"p99={p99:.3f}ms, max={max_lat:.3f}ms")
                
                # 健康检查
                if p99 > 5.0:
                    logger.warning("[Health] 系统延迟过高，建议检查负载")
    
    def should_retrain(self) -> bool:
        """判断是否需要重训练模型"""
        # 简化的判断逻辑：可以根据实际表现调整
        return self.tick_count > 0 and self.tick_count % 5000 == 0
    
    async def execute_strategy(self, tick: MarketTick, regime: RegimePrediction):
        """执行交易策略（简化示例）"""
        # 这里接入实际的交易逻辑
        # 例如：根据 regime 调整仓位、发送订单等
        pass
    
    async def stop(self):
        """优雅关闭"""
        logger.info("[Phase 3/3] 优雅关闭...")
        self.is_running = False
        
        # 2. 重要提醒：释放进程资源
        self.detector.shutdown()
        logger.info("✅ 已清理进程资源")
        
        # 最终报告
        if self.latency_buffer:
            logger.info(f"[Summary] 总 Ticks: {self.tick_count}")
            logger.info(f"[Summary] 平均延迟: {np.mean(self.latency_buffer):.3f}ms")
            logger.info(f"[Summary] p99 延迟: {np.percentile(self.latency_buffer, 99):.3f}ms")


async def main():
    """入口函数"""
    orchestrator = TradingOrchestrator()
    
    try:
        await orchestrator.start()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，正在关闭...")
        await orchestrator.stop()


if __name__ == "__main__":
    # 运行示例
    asyncio.run(main())
