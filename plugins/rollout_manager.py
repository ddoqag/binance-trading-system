#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灰度上线机制 - Rollout Manager
支持插件的渐进式灰度发布、版本控制和回滚
"""

import logging
from typing import Dict, Any, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta


class RolloutStage(Enum):
    """
    灰度上线阶段
    """
    DEVELOPMENT = "development"    # 开发阶段（内部测试）
    ALPHA = "alpha"              # 阿尔法测试（少量用户）
    BETA = "beta"                # 贝塔测试（部分用户）
    RC = "rc"                    # 候选发布版本（预发布）
    GA = "ga"                    # 正式发布（全面可用）


class RolloutStrategy(Enum):
    """
    灰度上线策略
    """
    MANUAL = "manual"            # 手动控制
    PERCENTAGE = "percentage"    # 按比例发布
    USER_SEGMENT = "user_segment"  # 用户分群
    CANARY = "canary"            # 金丝雀发布


class RolloutStatus(Enum):
    """
    上线状态
    """
    PENDING = "pending"          # 待开始
    IN_PROGRESS = "in_progress"  # 进行中
    COMPLETED = "completed"      # 已完成
    PAUSED = "paused"            # 已暂停
    FAILED = "failed"           # 失败


@dataclass
class RolloutMetrics:
    """
    上线指标
    """
    total_requests: int = 0
    success_requests: int = 0
    error_requests: int = 0
    latency_ms: float = 0.0
    user_count: int = 0
    performance_score: float = 100.0
    error_rate: float = 0.0
    user_satisfaction: float = 100.0
    metrics: Dict[str, Any] = field(default_factory=dict)

    def calculate_error_rate(self) -> float:
        """计算错误率"""
        if self.total_requests > 0:
            return (self.error_requests / self.total_requests) * 100
        return 0.0

    def update_metrics(self, success: bool, latency: float = 0.0):
        """更新指标"""
        self.total_requests += 1
        if success:
            self.success_requests += 1
        else:
            self.error_requests += 1

        if latency > 0:
            self.latency_ms = (self.latency_ms * (self.total_requests - 1) + latency) / self.total_requests


@dataclass
class RolloutPlan:
    """
    灰度上线计划
    """
    name: str
    version: str
    description: str
    stages: List[RolloutStage] = field(default_factory=list)
    strategy: RolloutStrategy = RolloutStrategy.PERCENTAGE
    config: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    current_stage: Optional[RolloutStage] = None
    metrics: RolloutMetrics = field(default_factory=RolloutMetrics)
    completion_criteria: Dict[str, Any] = field(default_factory=dict)
    on_complete: Optional[Callable] = None


class RolloutManager:
    """
    灰度上线管理器
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化灰度上线管理器

        Args:
            config: 配置
        """
        self.config = config or {
            "default_strategy": "percentage",
            "rollout_timeout": 3600,
            "error_threshold": 5.0,
            "latency_threshold": 1000
        }

        self.logger = logging.getLogger('Plugin.RolloutManager')
        self._plans: Dict[str, RolloutPlan] = {}
        self._active_plugins: Dict[str, str] = {}  # plugin_name: version
        self._plugin_versions: Dict[str, List[str]] = {}  # plugin_name: [versions]
        self._version_routes: Dict[str, List[Dict[str, Any]]] = {}

        self.logger.info("RolloutManager initialized")

    def register_version(self, plugin_name: str, version: str,
                       dependencies: Optional[List[str]] = None):
        """
        注册插件版本

        Args:
            plugin_name: 插件名称
            version: 版本号
            dependencies: 依赖列表
        """
        if plugin_name not in self._plugin_versions:
            self._plugin_versions[plugin_name] = []

        if version not in self._plugin_versions[plugin_name]:
            self._plugin_versions[plugin_name].append(version)
            self._plugin_versions[plugin_name].sort()  # 按版本号排序

        if plugin_name not in self._active_plugins:
            self._active_plugins[plugin_name] = version

        self.logger.debug(f"Registered plugin version: {plugin_name} v{version}")

    def create_rollout_plan(self, name: str, version: str,
                           description: str, strategy: RolloutStrategy,
                           config: Dict[str, Any]) -> RolloutPlan:
        """
        创建上线计划

        Args:
            name: 计划名称
            version: 目标版本
            description: 描述
            strategy: 上线策略
            config: 策略配置

        Returns:
            上线计划
        """
        plan = RolloutPlan(
            name=name,
            version=version,
            description=description,
            strategy=strategy,
            config=config,
            start_time=datetime.now(),
            current_stage=RolloutStage.DEVELOPMENT
        )

        self._plans[name] = plan
        self.logger.info(f"Created rollout plan: {name} (v{version})")

        return plan

    def start_rollout(self, plan_name: str) -> bool:
        """
        开始上线

        Args:
            plan_name: 计划名称

        Returns:
            是否成功开始
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return False

        plan = self._plans[plan_name]
        plan.current_stage = RolloutStage.ALPHA
        plan.metrics = RolloutMetrics()
        plan.start_time = datetime.now()

        self.logger.info(f"Started rollout: {plan_name} (v{plan.version})")
        return True

    def update_rollout_stage(self, plan_name: str, stage: RolloutStage) -> bool:
        """
        更新上线阶段

        Args:
            plan_name: 计划名称
            stage: 目标阶段

        Returns:
            是否成功更新
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return False

        plan = self._plans[plan_name]

        # 如果当前阶段是暂停状态（None），允许恢复到任何阶段
        if plan.current_stage is None:
            plan.current_stage = stage
            self.logger.info(f"Rollout resumed: {plan_name} -> {stage.value}")
            return True

        if plan.current_stage.value < stage.value:
            plan.current_stage = stage
            self.logger.info(f"Updated rollout stage: {plan_name} -> {stage.value}")
            return True
        else:
            self.logger.warning(f"Cannot downgrade rollout stage from {plan.current_stage.value} to {stage.value}")
            return False

    def pause_rollout(self, plan_name: str) -> bool:
        """
        暂停上线

        Args:
            plan_name: 计划名称

        Returns:
            是否成功暂停
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return False

        plan = self._plans[plan_name]
        # 保存当前阶段，标记为已暂停
        plan._previous_stage = plan.current_stage
        plan.current_stage = None
        self.logger.warning(f"Rollout paused: {plan_name}")
        return True

    def rollback_rollout(self, plan_name: str, target_version: str = None) -> bool:
        """
        回滚上线

        Args:
            plan_name: 计划名称
            target_version: 目标版本

        Returns:
            是否成功回滚
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return False

        plan = self._plans[plan_name]
        plugin_name = plan.name.split('_')[0]  # 从计划名称中提取插件名称

        if target_version:
            if target_version in self._plugin_versions.get(plugin_name, []):
                self._active_plugins[plugin_name] = target_version
                self.logger.warning(f"Rolled back {plugin_name} to v{target_version}")
            else:
                self.logger.error(f"Target version {target_version} not registered")
                return False
        else:
            # 回滚到之前的版本
            versions = self._plugin_versions.get(plugin_name, [])
            if len(versions) > 1:
                current_index = versions.index(self._active_plugins[plugin_name])
                previous_version = versions[max(0, current_index - 1)]
                self._active_plugins[plugin_name] = previous_version
                self.logger.warning(f"Rolled back {plugin_name} to v{previous_version}")

        plan.current_stage = RolloutStage.GA
        return True

    def check_health(self, plan_name: str) -> bool:
        """
        检查上线健康状态

        Args:
            plan_name: 计划名称

        Returns:
            是否健康
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return False

        plan = self._plans[plan_name]
        metrics = plan.metrics

        # 检查错误率
        if metrics.calculate_error_rate() > self.config.get("error_threshold", 5.0):
            self.logger.error(f"Error rate ({metrics.calculate_error_rate():.2f}%) exceeds threshold")
            self.pause_rollout(plan_name)
            return False

        # 检查延迟
        if metrics.latency_ms > self.config.get("latency_threshold", 1000):
            self.logger.error(f"Latency ({metrics.latency_ms:.2f}ms) exceeds threshold")
            self.pause_rollout(plan_name)
            return False

        # 检查性能分数
        if metrics.performance_score < 80:
            self.logger.warning(f"Performance score ({metrics.performance_score:.2f}) below expected")

        return True

    def route_request(self, plugin_name: str, user_id: Optional[str] = None,
                     request_id: Optional[str] = None) -> str:
        """
        请求路由

        Args:
            plugin_name: 插件名称
            user_id: 用户ID
            request_id: 请求ID

        Returns:
            应使用的版本号
        """
        # 找到最佳匹配的版本
        # 根据路由策略确定使用哪个版本
        if plugin_name not in self._active_plugins:
            self.logger.error(f"Plugin {plugin_name} not registered")
            return "default"

        active_version = self._active_plugins[plugin_name]
        return active_version

    def get_plan_status(self, plan_name: str) -> Dict[str, Any]:
        """
        获取计划状态

        Args:
            plan_name: 计划名称

        Returns:
            状态信息
        """
        if plan_name not in self._plans:
            return {
                "status": "error",
                "message": "Plan not found"
            }

        plan = self._plans[plan_name]
        metrics = plan.metrics

        status = RolloutStatus.IN_PROGRESS.value
        stage_value = "paused"

        if plan.current_stage is not None:
            stage_value = plan.current_stage.value
            if plan.current_stage.value >= RolloutStage.GA.value:
                status = RolloutStatus.COMPLETED.value
        else:
            status = RolloutStatus.PAUSED.value

        return {
            "plan_name": plan_name,
            "version": plan.version,
            "stage": stage_value,
            "status": status,
            "start_time": plan.start_time.isoformat(),
            "duration": str(datetime.now() - plan.start_time),
            "metrics": {
                "total_requests": metrics.total_requests,
                "success_rate": (metrics.success_requests / metrics.total_requests) * 100 if metrics.total_requests > 0 else 0,
                "error_rate": metrics.calculate_error_rate(),
                "latency": metrics.latency_ms,
                "user_count": metrics.user_count,
                "performance_score": metrics.performance_score
            }
        }

    def get_all_plans(self) -> Dict[str, RolloutPlan]:
        """
        获取所有计划

        Returns:
            所有计划的字典
        """
        return self._plans.copy()

    def get_version_info(self, plugin_name: str) -> Dict[str, Any]:
        """
        获取插件版本信息

        Args:
            plugin_name: 插件名称

        Returns:
            版本信息
        """
        if plugin_name not in self._plugin_versions:
            return {"versions": [], "active": None}

        return {
            "versions": self._plugin_versions[plugin_name],
            "active": self._active_plugins.get(plugin_name),
            "latest": self._plugin_versions[plugin_name][-1]
        }

    def create_canary_rollout(self, plugin_name: str,
                            new_version: str,
                            user_percentage: float = 10.0,
                            duration: int = 3600) -> RolloutPlan:
        """
        创建金丝雀发布计划

        Args:
            plugin_name: 插件名称
            new_version: 新版本
            user_percentage: 用户比例
            duration: 持续时间（秒）

        Returns:
            上线计划
        """
        self.register_version(plugin_name, new_version)

        plan_name = f"{plugin_name}_canary_{new_version}"

        return self.create_rollout_plan(
            name=plan_name,
            version=new_version,
            description=f"Canary rollout for {plugin_name} v{new_version}",
            strategy=RolloutStrategy.CANARY,
            config={
                "plugin_name": plugin_name,
                "user_percentage": user_percentage,
                "duration": duration
            }
        )

    def update_traffic_split(self, plan_name: str, percentage: float):
        """
        更新流量分配

        Args:
            plan_name: 计划名称
            percentage: 流量比例
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return

        self._plans[plan_name].config["user_percentage"] = percentage
        self.logger.info(f"Updated traffic split for {plan_name} to {percentage}%")

    def complete_rollout(self, plan_name: str):
        """
        完成上线

        Args:
            plan_name: 计划名称
        """
        if plan_name not in self._plans:
            self.logger.error(f"Plan not found: {plan_name}")
            return

        plan = self._plans[plan_name]
        plan.current_stage = RolloutStage.GA
        plan.end_time = datetime.now()

        # 更新为默认版本
        self._active_plugins[plan.name.split('_')[0]] = plan.version
        self.logger.info(f"Rollout completed: {plan_name}")
