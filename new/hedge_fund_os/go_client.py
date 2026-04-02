"""
Hedge Fund OS - Go 引擎 HTTP 客户端

用于从 Go 后端获取 PnL 和系统指标
"""

import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime

from .risk_kernel import PnLSignal, SystemMetrics


logger = logging.getLogger(__name__)


class GoEngineClient:
    """
    Go 引擎 HTTP 客户端
    
    用于 Risk Kernel 轮询获取 PnL 和系统指标
    """
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 2.0  # 2秒超时
        
    def get_risk_stats(self) -> Optional[PnLSignal]:
        """获取风险统计数据"""
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/risk/stats")
            resp.raise_for_status()
            data = resp.json()
            
            if "error" in data:
                logger.error(f"Risk stats error: {data['error']}")
                return None
                
            return PnLSignal.from_dict(data)
        except requests.RequestException as e:
            logger.debug(f"Failed to get risk stats: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting risk stats: {e}")
            return None
            
    def get_system_metrics(self) -> Optional[SystemMetrics]:
        """获取系统指标"""
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/system/metrics")
            resp.raise_for_status()
            data = resp.json()
            return SystemMetrics.from_dict(data)
        except requests.RequestException as e:
            logger.debug(f"Failed to get system metrics: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting system metrics: {e}")
            return None
            
    def get_status(self) -> Optional[Dict[str, Any]]:
        """获取引擎状态"""
        try:
            resp = self.session.get(f"{self.base_url}/api/v1/status")
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.debug(f"Failed to get status: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting status: {e}")
            return None
            
    def is_healthy(self) -> bool:
        """检查 Go 引擎是否健康"""
        status = self.get_status()
        if status is None:
            return False
        return status.get("connected", False)


class MockGoEngineClient:
    """
    Mock Go 引擎客户端（用于测试）
    """
    
    def __init__(self):
        self._pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
        )
        self._metrics = SystemMetrics(
            timestamp=datetime.now(),
            memory_usage_gb=1.0,
            memory_usage_percent=30.0,
            ws_latency_ms=50.0,
            rate_limit_hits_1min=0,
            cpu_usage=10.0,
            open_orders=0,
        )
        self._healthy = True
        
    def set_pnl(self, pnl: PnLSignal) -> None:
        """设置 Mock PnL 数据"""
        self._pnl = pnl
        
    def set_metrics(self, metrics: SystemMetrics) -> None:
        """设置 Mock 系统指标"""
        self._metrics = metrics
        
    def set_healthy(self, healthy: bool) -> None:
        """设置健康状态"""
        self._healthy = healthy
        
    def get_risk_stats(self) -> Optional[PnLSignal]:
        return self._pnl if self._healthy else None
        
    def get_system_metrics(self) -> Optional[SystemMetrics]:
        return self._metrics if self._healthy else None
        
    def get_status(self) -> Optional[Dict[str, Any]]:
        if not self._healthy:
            return None
        return {"connected": True, "symbol": "BTCUSDT"}
        
    def is_healthy(self) -> bool:
        return self._healthy
