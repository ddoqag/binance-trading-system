#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PPO 智能体插件 - Proximal Policy Optimization Agent Plugin
实现近端策略优化强化学习算法的插件化
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List

from plugins.base import PluginBase, PluginType, PluginMetadata, PluginHealthStatus
from rl.environment import TradingEnvironment, EnvironmentConfig
from rl.agents.ppo import PPOAgent


class PPOAgentPlugin(PluginBase):
    """
    PPO 智能体插件
    实现近端策略优化强化学习算法的插件化
    """

    def _get_metadata(self) -> PluginMetadata:
        """获取插件元数据"""
        return PluginMetadata(
            name="PPOAgentPlugin",
            version="1.0.0",
            type=PluginType.EXECUTION,
            interface_version="1.0.0",
            description="Proximal Policy Optimization (PPO) reinforcement learning agent for trading",
            author="Binance Trading System",
            config_schema={
                "properties": {
                    "learning_rate": {"type": "number", "default": 0.0003},
                    "gamma": {"type": "number", "default": 0.99},
                    "gae_lambda": {"type": "number", "default": 0.95},
                    "clip_ratio": {"type": "number", "default": 0.2},
                    "target_kl": {"type": "number", "default": 0.01},
                    "vf_coef": {"type": "number", "default": 0.5},
                    "ent_coef": {"type": "number", "default": 0.01},
                    "batch_size": {"type": "integer", "default": 128},
                    "epochs": {"type": "integer", "default": 10},
                    "max_steps": {"type": "integer", "default": 5000},
                    "hidden_layers": {"type": "array", "default": [128, 64, 32]},
                    "train_episodes": {"type": "integer", "default": 100},
                    "valid_episodes": {"type": "integer", "default": 20},
                    "window_size": {"type": "integer", "default": 20},
                    "initial_capital": {"type": "number", "default": 10000.0},
                    "commission_rate": {"type": "number", "default": 0.001},
                    "slippage": {"type": "number", "default": 0.0005},
                    "reward_type": {"type": "string", "default": "risk_adjusted"}
                }
            }
        )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """初始化 PPO 智能体插件"""
        super().__init__(config)
        self.agent = None
        self.environment = None
        self.is_trained = False

        # 代理配置
        self.learning_rate = self.config.get("learning_rate", 0.0003)
        self.gamma = self.config.get("gamma", 0.99)
        self.gae_lambda = self.config.get("gae_lambda", 0.95)
        self.clip_ratio = self.config.get("clip_ratio", 0.2)
        self.target_kl = self.config.get("target_kl", 0.01)
        self.vf_coef = self.config.get("vf_coef", 0.5)
        self.ent_coef = self.config.get("ent_coef", 0.01)
        self.batch_size = self.config.get("batch_size", 128)
        self.epochs = self.config.get("epochs", 10)
        self.max_steps = self.config.get("max_steps", 5000)
        self.hidden_layers = self.config.get("hidden_layers", [128, 64, 32])
        self.train_episodes = self.config.get("train_episodes", 100)
        self.valid_episodes = self.config.get("valid_episodes", 20)

        # 环境配置
        self.window_size = self.config.get("window_size", 20)
        self.initial_capital = self.config.get("initial_capital", 10000.0)
        self.commission_rate = self.config.get("commission_rate", 0.001)
        self.slippage = self.config.get("slippage", 0.0005)
        self.reward_type = self.config.get("reward_type", "risk_adjusted")

    def initialize(self):
        """初始化插件"""
        self.logger.info("PPO agent plugin initialized")
        self.logger.debug(f"Configuration: lr={self.learning_rate}, "
                        f"gamma={self.gamma}, clip_ratio={self.clip_ratio}")

        # 订阅事件
        self.subscribe_event("data.loaded", self._on_data_loaded)
        self.subscribe_event("model.trained", self._on_model_trained)
        self.subscribe_event("training.completed", self._on_training_completed)

    def start(self):
        """启动插件"""
        self.logger.info("PPO agent plugin started")

    def stop(self):
        """停止插件"""
        self.logger.info("PPO agent plugin stopped")
        self._cleanup()

    def _on_data_loaded(self, event: Dict[str, Any]):
        """处理数据加载事件"""
        try:
            if "dataframe" in event:
                self.logger.debug(f"Data loaded: {event.get('records_count', 0)} records")
                self._create_environment(event["dataframe"])
            elif "file_path" in event:
                # 从文件加载数据
                df = pd.read_csv(event["file_path"], index_col=0, parse_dates=True)
                self._create_environment(df)
        except Exception as e:
            self.logger.error(f"Failed to process data loaded event: {e}")

    def _on_model_trained(self, event: Dict[str, Any]):
        """处理模型训练事件"""
        if event.get("agent_name") == self.metadata.name:
            self.logger.info("Model trained successfully")
            self.is_trained = True
            self.emit_event("agent.ready", {"agent_name": self.metadata.name})

    def _on_training_completed(self, event: Dict[str, Any]):
        """处理训练完成事件"""
        if event.get("agent_name") == self.metadata.name:
            self.logger.info(f"Training completed in {event.get('training_time', 'N/A')}")
            self.is_trained = True

    def _create_environment(self, df: pd.DataFrame):
        """创建交易环境"""
        try:
            config = EnvironmentConfig(
                initial_capital=self.initial_capital,
                commission_rate=self.commission_rate,
                slippage=self.slippage,
                reward_type=self.reward_type,
                window_size=self.window_size
            )

            self.environment = TradingEnvironment(df, config)
            self.logger.debug("Trading environment created successfully")
            self.emit_event("environment.created", {"window_size": self.window_size})
        except Exception as e:
            self.logger.error(f"Failed to create environment: {e}")

    def _create_agent(self):
        """创建 PPO 智能体"""
        if self.environment is None:
            raise Exception("Environment not created. Please load data first.")

        # 初始化 PPO 智能体
        state_dim = self.environment.get_state_dim()
        action_dim = self.environment.get_action_dim()

        self.agent = PPOAgent(
            state_dim=state_dim,
            action_dim=action_dim,
            learning_rate=self.learning_rate,
            gamma=self.gamma,
            gae_lambda=self.gae_lambda,
            clip_ratio=self.clip_ratio,
            target_kl=self.target_kl,
            vf_coef=self.vf_coef,
            ent_coef=self.ent_coef,
            batch_size=self.batch_size,
            epochs=self.epochs,
            hidden_layers=self.hidden_layers
        )

        self.logger.debug("PPO agent created")
        return self.agent

    def train(self) -> Dict[str, Any]:
        """训练 PPO 智能体"""
        if self.environment is None:
            raise Exception("Environment not created. Please load data first.")

        self._create_agent()

        self.logger.info("Starting PPO agent training")
        self.emit_event("training.started", {"agent_name": self.metadata.name})

        training_results = {}
        try:
            # 训练过程
            training_results = self._run_training()
            self.is_trained = True

            self.logger.info(f"Training completed. Total rewards: {training_results.get('total_rewards', 0):.2f}")
            self.emit_event("training.completed", {
                "agent_name": self.metadata.name,
                "training_time": training_results.get("training_time"),
                "total_rewards": training_results.get("total_rewards")
            })
        except Exception as e:
            self.logger.error(f"Training failed: {e}")
            self.emit_event("training.failed", {
                "agent_name": self.metadata.name,
                "error": str(e)
            })

        return training_results

    def _run_training(self) -> Dict[str, Any]:
        """执行训练过程"""
        from rl.training import train_agent

        training_results = train_agent(
            self.agent,
            self.environment,
            self.train_episodes,
            self.valid_episodes
        )

        return training_results

    def predict(self, state: np.ndarray) -> int:
        """
        使用训练好的模型进行预测

        Args:
            state: 当前状态

        Returns:
            动作索引：0=卖出，1=持有，2=买入
        """
        if not self.is_trained or self.agent is None:
            raise Exception("Agent not trained. Please train first.")

        try:
            action = self.agent.predict(state)
            return int(action)
        except Exception as e:
            self.logger.error(f"Prediction failed: {e}")
            return 1  # 默认持有

    def get_trading_signal(self, state: np.ndarray) -> Dict[str, Any]:
        """
        生成交易信号

        Args:
            state: 当前状态

        Returns:
            交易信号：包含类型、价格、数量等
        """
        action = self.predict(state)
        signal = self._interpret_action(action)
        return signal

    def _interpret_action(self, action: int) -> Dict[str, Any]:
        """解释动作"""
        actions = {
            0: "SELL",
            1: "HOLD",
            2: "BUY"
        }

        # 获取当前价格信息
        current_price = 0.0
        if self.environment:
            current_price = self.environment.df['close'].iloc[-1]

        return {
            "signal": actions.get(action, "HOLD"),
            "type": "RL",
            "price": current_price,
            "size": 0.1 if action != 1 else 0
        }

    def evaluate(self) -> Dict[str, Any]:
        """评估智能体性能"""
        if not self.is_trained or self.environment is None:
            return {"error": "Agent not trained"}

        try:
            from rl.training import evaluate_agent
            metrics = evaluate_agent(self.agent, self.environment)

            # 格式化结果
            result = {
                "total_reward": float(metrics['total_reward']),
                "total_profit": float(metrics['total_profit']),
                "sharpe_ratio": float(metrics['sharpe_ratio']),
                "max_drawdown": float(metrics['max_drawdown']),
                "profit_factor": float(metrics['profit_factor']),
                "trade_count": int(metrics['trade_count'])
            }

            self.emit_event("agent.evaluated", {
                "agent_name": self.metadata.name,
                "metrics": result
            })

            return result
        except Exception as e:
            self.logger.error(f"Evaluation failed: {e}")
            return {"error": str(e)}

    def save_model(self, file_path: str) -> bool:
        """保存模型"""
        try:
            if self.agent:
                self.agent.save_model(file_path)
                self.logger.info(f"Model saved to {file_path}")
                self.emit_event("model.saved", {"file_path": file_path})
                return True
            raise Exception("Agent not created")
        except Exception as e:
            self.logger.error(f"Failed to save model: {e}")
            return False

    def load_model(self, file_path: str) -> bool:
        """加载模型"""
        try:
            if self.agent is None and self.environment is not None:
                self._create_agent()

            if self.agent:
                self.agent.load_model(file_path)
                self.is_trained = True
                self.logger.info(f"Model loaded from {file_path}")
                self.emit_event("model.loaded", {"file_path": file_path})
                self.emit_event("agent.ready", {"agent_name": self.metadata.name})
                return True
            raise Exception("Environment not created")
        except Exception as e:
            self.logger.error(f"Failed to load model: {e}")
            return False

    def health_check(self) -> PluginHealthStatus:
        """健康检查"""
        status = super().health_check()
        status.metrics.update({
            "agent_created": self.agent is not None,
            "environment_created": self.environment is not None,
            "is_trained": self.is_trained,
            "train_episodes": self.train_episodes,
            "valid_episodes": self.valid_episodes
        })

        if not self.environment:
            status.healthy = False
            status.message = "Environment not initialized"
        elif not self.is_trained:
            status.healthy = False
            status.message = "Agent not trained"

        return status

    def _cleanup(self):
        """清理资源"""
        if self.agent:
            del self.agent
            self.agent = None
        if self.environment:
            del self.environment
            self.environment = None

    def get_training_config(self) -> Dict[str, Any]:
        """获取训练配置"""
        return {
            "learning_rate": self.learning_rate,
            "gamma": self.gamma,
            "gae_lambda": self.gae_lambda,
            "clip_ratio": self.clip_ratio,
            "target_kl": self.target_kl,
            "vf_coef": self.vf_coef,
            "ent_coef": self.ent_coef,
            "batch_size": self.batch_size,
            "epochs": self.epochs,
            "max_steps": self.max_steps,
            "hidden_layers": self.hidden_layers,
            "train_episodes": self.train_episodes,
            "valid_episodes": self.valid_episodes
        }

    def set_training_config(self, config: Dict[str, Any]):
        """设置训练配置"""
        for key, value in config.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.logger.debug("Training configuration updated")
