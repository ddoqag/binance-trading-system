"""
策略基类单元测试
"""

from typing import Any

import pandas as pd
import pytest

from strategy.base import BaseStrategy


class MockStrategy(BaseStrategy):
    """模拟策略实现，用于测试"""

    def generate_signals(self, df: pd.DataFrame):
        """生成买入信号"""
        df = df.copy()
        df['signal'] = 0
        df.loc[df['close'] > df['close'].shift(1), 'signal'] = 1
        df.loc[df['close'] < df['close'].shift(1), 'signal'] = -1
        return df


class TestBaseStrategy:
    """测试策略基类"""

    def test_default_initialization(self):
        """测试默认初始化"""
        strategy = MockStrategy("test_strategy")

        assert strategy.name == "test_strategy"
        assert strategy.params == {}
        assert strategy.position == 0
        assert strategy.last_signal == 0
        assert strategy.logger.name == "Strategy.test_strategy"

    def test_custom_initialization(self):
        """测试自定义初始化"""
        params = {
            "period": 20,
            "threshold": 0.5
        }
        strategy = MockStrategy("custom_strategy", params)

        assert strategy.name == "custom_strategy"
        assert strategy.params == params
        assert strategy.params["period"] == 20
        assert strategy.params["threshold"] == 0.5

    def test_get_params(self):
        """测试获取参数"""
        params = {"key1": "value1", "key2": 123}
        strategy = MockStrategy("test", params)

        result = strategy.get_params()

        assert result == params
        # 确保返回的是副本
        result["new_key"] = "new_value"
        assert "new_key" not in strategy.params

    def test_set_params(self):
        """测试设置参数"""
        strategy = MockStrategy("test")

        strategy.set_params({"param1": 1, "param2": 2})
        assert strategy.params == {"param1": 1, "param2": 2}

        # 测试更新现有参数
        strategy.set_params({"param1": 10})
        assert strategy.params == {"param1": 10, "param2": 2}

        # 测试添加新参数
        strategy.set_params({"param3": 3})
        assert strategy.params == {"param1": 10, "param2": 2, "param3": 3}

    def test_reset(self):
        """测试重置策略状态"""
        strategy = MockStrategy("test")

        # 修改状态
        strategy.position = 1
        strategy.last_signal = 1

        # 重置
        strategy.reset()

        # 验证状态已重置
        assert strategy.position == 0
        assert strategy.last_signal == 0

    def test_generate_signals_abstract(self):
        """测试抽象方法必须实现"""

        class IncompleteStrategy(BaseStrategy):
            pass

        with pytest.raises(TypeError):
            IncompleteStrategy("incomplete")

    def test_generate_signals(self):
        """测试生成信号"""
        strategy = MockStrategy("test")

        # 创建测试数据
        df = pd.DataFrame({
            'open': [100, 101, 102, 101, 103],
            'high': [102, 103, 104, 103, 105],
            'low': [99, 100, 101, 100, 102],
            'close': [101, 102, 101, 103, 104],
            'volume': [1000, 1500, 1200, 1800, 2000]
        })

        result = strategy.generate_signals(df)

        assert 'signal' in result.columns
        assert len(result) == len(df)

    def test_strategy_with_none_params(self):
        """测试 None 参数处理"""
        strategy = MockStrategy("test", None)
        assert strategy.params == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
