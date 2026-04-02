"""
P10 Hedge Fund OS - 决策日志记录器

价值：为未来的 Evolution Engine 提供带标签的实盘数据

记录内容：
- 每分钟的 MetaDecision (策略选择、权重、风险偏好)
- 市场状态上下文 (Regime、ATR、Volume Z-Score)
- Capital Allocator 的分配结果
- Risk Kernel 的风险评估

格式：JSON Lines (JSONL) - 每行一个JSON对象，便于追加和流式处理
"""

import json
import time
import os
from typing import Dict, Any, Optional
from datetime import datetime
from dataclasses import asdict, is_dataclass
from pathlib import Path
import threading


class DecisionLogger:
    """
    决策日志记录器
    
    设计原则：
    1. 零拷贝：异步写入，不阻塞主交易循环
    2. 崩溃安全：每条记录独立一行，部分写入可恢复
    3. 可查询：JSONL格式支持grep/awk快速过滤
    4. 带标签：记录完整市场上下文，用于后续监督学习
    """
    
    def __init__(self, 
                 log_dir: str = "logs/decisions",
                 max_file_size_mb: float = 100,
                 buffer_size: int = 100):
        """
        Args:
            log_dir: 日志目录
            max_file_size_mb: 单个文件最大大小
            buffer_size: 内存缓冲区大小 (条数)
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.buffer_size = buffer_size
        
        # 当前文件
        self.current_file: Optional[Path] = None
        self.current_size = 0
        
        # 内存缓冲区
        self._buffer: list = []
        self._buffer_lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 统计
        self.records_written = 0
        self.bytes_written = 0
        
        # 启动后台刷新线程
        self._start_flush_thread()
    
    def _get_new_file(self) -> Path:
        """生成新的日志文件路径"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.log_dir / f"decisions_{timestamp}.jsonl"
    
    def _ensure_file(self):
        """确保当前文件可用"""
        if self.current_file is None or \
           (self.current_file.exists() and self.current_file.stat().st_size > self.max_file_size):
            self._flush_buffer()  # 先刷新旧文件
            self.current_file = self._get_new_file()
            self.current_size = 0
            print(f"[DecisionLogger] New log file: {self.current_file}")
    
    def log_decision(self,
                     timestamp: datetime,
                     cycle: int,
                     market_state: Any,
                     meta_decision: Any,
                     allocation_plan: Any,
                     risk_metrics: Dict[str, float],
                     latency_ms: Dict[str, float]):
        """
        记录完整决策快照
        
        这是核心方法，记录一次决策循环的所有上下文
        """
        record = {
            # 基础信息
            'timestamp': timestamp.isoformat(),
            'unix_time': time.time(),
            'cycle': cycle,
            
            # 市场状态上下文 (用于Evolution Engine的标签)
            'market_context': self._extract_market_context(market_state),
            
            # Meta Brain 决策
            'decision': self._extract_decision(meta_decision),
            
            # Capital Allocator 输出
            'allocation': self._extract_allocation(allocation_plan),
            
            # Risk Kernel 评估
            'risk': risk_metrics,
            
            # 性能指标
            'latency_ms': latency_ms,
            
            # 系统状态
            'system': {
                'pid': os.getpid(),
                'thread_id': threading.current_thread().ident,
            }
        }
        
        with self._buffer_lock:
            self._buffer.append(record)
            
            # 缓冲区满时立即刷新
            if len(self._buffer) >= self.buffer_size:
                self._flush_buffer_unlocked()
    
    def _extract_market_context(self, market_state: Any) -> Dict[str, Any]:
        """提取市场状态上下文"""
        if market_state is None:
            return {}
        
        context = {}
        
        # 基础regime信息
        if hasattr(market_state, 'regime'):
            context['regime'] = market_state.regime.value if hasattr(market_state.regime, 'value') else str(market_state.regime)
        
        if hasattr(market_state, 'volatility'):
            context['volatility'] = float(market_state.volatility)
        
        if hasattr(market_state, 'trend'):
            context['trend'] = str(market_state.trend)
        
        # 扩展指标 (用于Evolution Engine的特征工程)
        if hasattr(market_state, 'macro_signals'):
            context['macro_signals'] = dict(market_state.macro_signals)
        
        # 如果有ATR、Volume Z-Score等技术指标
        if hasattr(market_state, 'atr_14'):
            context['atr_14'] = float(market_state.atr_14)
        
        if hasattr(market_state, 'volume_zscore'):
            context['volume_zscore'] = float(market_state.volume_zscore)
        
        if hasattr(market_state, 'rsi_14'):
            context['rsi_14'] = float(market_state.rsi_14)
        
        return context
    
    def _extract_decision(self, decision: Any) -> Dict[str, Any]:
        """提取决策信息"""
        if decision is None:
            return {}
        
        result = {}
        
        if hasattr(decision, 'selected_strategies'):
            result['selected_strategies'] = list(decision.selected_strategies)
        
        if hasattr(decision, 'strategy_weights'):
            result['strategy_weights'] = dict(decision.strategy_weights)
        
        if hasattr(decision, 'risk_appetite'):
            result['risk_appetite'] = decision.risk_appetite.name if hasattr(decision.risk_appetite, 'name') else str(decision.risk_appetite)
        
        if hasattr(decision, 'target_exposure'):
            result['target_exposure'] = float(decision.target_exposure)
        
        if hasattr(decision, 'mode'):
            result['target_mode'] = decision.mode.name if hasattr(decision.mode, 'name') else str(decision.mode)
        
        if hasattr(decision, 'leverage'):
            result['leverage'] = float(decision.leverage)
        
        return result
    
    def _extract_allocation(self, plan: Any) -> Dict[str, Any]:
        """提取分配计划"""
        if plan is None:
            return {}
        
        result = {}
        
        if hasattr(plan, 'allocations'):
            result['allocations'] = dict(plan.allocations)
        
        if hasattr(plan, 'leverage'):
            result['leverage'] = float(plan.leverage)
        
        if hasattr(plan, 'max_drawdown_limit'):
            result['max_drawdown_limit'] = float(plan.max_drawdown_limit)
        
        return result
    
    def _flush_buffer(self):
        """刷新缓冲区到磁盘"""
        with self._buffer_lock:
            self._flush_buffer_unlocked()
    
    def _flush_buffer_unlocked(self):
        """无锁刷新 (必须在持有_buffer_lock时调用)"""
        if not self._buffer:
            return
        
        self._ensure_file()
        
        try:
            with open(self.current_file, 'a', encoding='utf-8') as f:
                for record in self._buffer:
                    json_line = json.dumps(record, ensure_ascii=False, default=str)
                    f.write(json_line + '\n')
                    self.current_size += len(json_line) + 1
                    self.records_written += 1
                    self.bytes_written += len(json_line) + 1
            
            self._buffer.clear()
            
        except Exception as e:
            print(f"[DecisionLogger] Flush error: {e}")
    
    def _start_flush_thread(self):
        """启动后台刷新线程"""
        def flush_loop():
            while not self._stop_event.is_set():
                self._stop_event.wait(timeout=5.0)  # 每5秒刷新一次
                self._flush_buffer()
        
        self._flush_thread = threading.Thread(target=flush_loop, daemon=True)
        self._flush_thread.start()
    
    def flush(self):
        """强制刷新缓冲区"""
        self._flush_buffer()
        print(f"[DecisionLogger] Force flushed. Total records: {self.records_written}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取日志统计"""
        return {
            'records_written': self.records_written,
            'bytes_written': self.bytes_written,
            'buffer_pending': len(self._buffer),
            'current_file': str(self.current_file) if self.current_file else None,
        }
    
    def close(self):
        """关闭记录器"""
        self._stop_event.set()
        self._flush_buffer()
        
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)
        
        print(f"[DecisionLogger] Closed. Total records: {self.records_written}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 便捷函数
def create_default_logger(log_dir: str = "logs/decisions") -> DecisionLogger:
    """创建默认决策日志记录器"""
    return DecisionLogger(log_dir=log_dir)


def quick_log_sample():
    """生成示例日志文件 (用于测试)"""
    from datetime import datetime
    
    with DecisionLogger(log_dir="logs/decisions_test") as logger:
        for i in range(10):
            logger.log_decision(
                timestamp=datetime.now(),
                cycle=i,
                market_state=None,
                meta_decision=None,
                allocation_plan=None,
                risk_metrics={'daily_drawdown': 0.05, 'leverage': 1.5},
                latency_ms={'meta_brain': 5.2, 'allocator': 2.1}
            )
            time.sleep(0.1)
        
        print(f"Stats: {logger.get_stats()}")


if __name__ == '__main__':
    quick_log_sample()
