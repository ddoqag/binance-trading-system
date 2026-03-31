"""
auto_strategy_synthesis.py - Phase 5: Auto-Strategy Synthesis

自动策略生成系统:
1. 策略模板组合
2. 算子级遗传编程
3. 表达式树进化
4. 策略验证和回测
"""

import random
import numpy as np
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum, auto
from abc import ABC, abstractmethod


class OpType(Enum):
    """算子类型"""
    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    GT = ">"
    LT = "<"
    AND = "and"
    OR = "or"
    NOT = "not"
    MA = "ma"      # 移动平均
    RSI = "rsi"    # RSI指标
    BB = "bb"      # 布林带
    MACD = "macd"  # MACD


class Node:
    """表达式树节点"""

    def __init__(self, op_type: OpType, children: List['Node'] = None, value=None):
        self.op_type = op_type
        self.children = children or []
        self.value = value  # 叶节点值

    def evaluate(self, context: Dict) -> float:
        """评估节点"""
        if self.op_type == OpType.ADD:
            return sum(c.evaluate(context) for c in self.children)
        elif self.op_type == OpType.MUL:
            result = 1
            for c in self.children:
                result *= c.evaluate(context)
            return result
        elif self.op_type == OpType.GT:
            return 1.0 if self.children[0].evaluate(context) > self.children[1].evaluate(context) else 0.0
        elif self.op_type == OpType.MA:
            period = int(self.children[1].evaluate(context)) if len(self.children) > 1 else 20
            prices = context.get('prices', [])
            if len(prices) >= period:
                return np.mean(prices[-period:])
            return prices[-1] if prices else 0.0
        elif self.value is not None:
            return float(self.value)
        return 0.0

    def to_string(self) -> str:
        """转换为可读字符串"""
        if self.value is not None:
            return str(self.value)
        if self.children:
            args = ", ".join(c.to_string() for c in self.children)
            return f"{self.op_type.value}({args})"
        return self.op_type.value


@dataclass
class StrategyTemplate:
    """策略模板"""
    name: str
    entry_condition: Node
    exit_condition: Node
    position_size: float = 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class StrategySynthesizer:
    """策略合成器"""

    def __init__(self, population_size: int = 50):
        self.population_size = population_size
        self.templates: List[StrategyTemplate] = []
        self.operators = [OpType.ADD, OpType.MUL, OpType.GT, OpType.LT, OpType.MA, OpType.RSI]

    def random_node(self, depth: int = 0, max_depth: int = 5) -> Node:
        """生成随机表达式树"""
        if depth >= max_depth or random.random() < 0.3:
            # 叶节点
            return Node(OpType.ADD, value=random.uniform(-1, 1))

        # 内部节点
        op = random.choice(self.operators)

        if op in [OpType.NOT]:
            children = [self.random_node(depth + 1, max_depth)]
        elif op in [OpType.MA, OpType.RSI]:
            children = [
                self.random_node(depth + 1, max_depth),
                Node(OpType.ADD, value=random.randint(5, 50))  # period
            ]
        else:
            children = [
                self.random_node(depth + 1, max_depth),
                self.random_node(depth + 1, max_depth)
            ]

        return Node(op, children)

    def synthesize(self, n_strategies: int = 10) -> List[StrategyTemplate]:
        """合成策略"""
        strategies = []
        for i in range(n_strategies):
            entry = self.random_node(max_depth=4)
            exit_cond = self.random_node(max_depth=3)

            strategy = StrategyTemplate(
                name=f"synth_{i}_{random.randint(1000, 9999)}",
                entry_condition=entry,
                exit_condition=exit_cond,
                position_size=random.uniform(0.1, 1.0),
                stop_loss=random.choice([0.02, 0.05, 0.1, None]),
                take_profit=random.choice([0.05, 0.1, 0.2, None])
            )
            strategies.append(strategy)

        return strategies

    def mutate(self, strategy: StrategyTemplate) -> StrategyTemplate:
        """变异策略"""
        # 随机变异某个条件
        if random.random() < 0.5:
            new_entry = self.random_node(max_depth=4)
        else:
            new_entry = strategy.entry_condition

        if random.random() < 0.5:
            new_exit = self.random_node(max_depth=3)
        else:
            new_exit = strategy.exit_condition

        return StrategyTemplate(
            name=f"{strategy.name}_mut",
            entry_condition=new_entry,
            exit_condition=new_exit,
            position_size=strategy.position_size * random.uniform(0.8, 1.2),
            stop_loss=strategy.stop_loss,
            take_profit=strategy.take_profit
        )


# 使用示例
if __name__ == "__main__":
    synth = StrategySynthesizer()

    # 合成策略
    strategies = synth.synthesize(5)

    for s in strategies:
        print(f"\nStrategy: {s.name}")
        print(f"  Entry: {s.entry_condition.to_string()}")
        print(f"  Exit: {s.exit_condition.to_string()}")

    # 测试评估
    context = {'prices': [100, 102, 101, 103, 105, 104, 106]}
    signal = strategies[0].entry_condition.evaluate(context)
    print(f"\nSignal: {signal}")
