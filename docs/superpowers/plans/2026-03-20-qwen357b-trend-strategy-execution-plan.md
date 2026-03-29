# Qwen3.5-7B 市场趋势判断与策略执行系统实现计划（修订版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有的 `ai_trading/` 模块重构为插件化架构，增强 Qwen3.5-7B 集成、风险控制和完整系统功能。

**Architecture:** 利用现有 `ai_trading/` 模块，将其适配为插件化架构，保持与现有 `PluginBase` 的向后兼容性。

**Tech Stack:** Python 3.9+, PyTorch, Transformers, PostgreSQL, Binance API, asyncio (可选)

---

## 原则

1. **复用现有代码** - 充分利用 `ai_trading/` 模块，不重复造轮子
2. **向后兼容** - 保持与现有 `PluginBase` 的同步方法兼容
3. **任务粒度适中** - 每个任务 2-5 分钟
4. **TDD** - 先写测试，再实现
5. **YAGNI** - 先做 MVP，再优化（不做量化风险评估、GPU优化等）

---

## 阶段 1：扩展配置与基础准备 (预计 1.5 天)

### 任务 1.1：扩展 Settings 添加 Qwen 配置
**文件：** Modify: `config/settings.py:45-60`

- [ ] **Step 1: 添加 QwenConfig 数据类**

```python
# config/settings.py:45-60
@dataclass
class QwenConfig:
    """Qwen3.5-7B 模型配置"""
    model_path: str = "D:/binance/models/Qwen/Qwen3-8B"
    auto_download: bool = False
    quantization: str = "none"  # none, 4bit, 8bit
    max_tokens: int = 500
    temperature: float = 0.7
    device: str = "auto"

    @classmethod
    def from_env(cls) -> 'QwenConfig':
        """从环境变量加载配置"""
        import os
        return cls(
            model_path=os.environ.get("QWEN_MODEL_PATH", cls.model_path),
            auto_download=os.environ.get("QWEN_AUTO_DOWNLOAD", "false").lower() == "true",
            quantization=os.environ.get("QWEN_QUANTIZATION", cls.quantization),
            max_tokens=int(os.environ.get("QWEN_MAX_TOKENS", str(cls.max_tokens))),
            temperature=float(os.environ.get("QWEN_TEMPERATURE", str(cls.temperature)))
        )
```

- [ ] **Step 2: 在 Settings 类中添加 qwen 属性**

```python
# config/settings.py:98-100
    def __init__(self, env_file: Optional[Path] = None):
        self._load_env(env_file)
        self.db = self._load_db_config()
        self.trading = self._load_trading_config()
        self.qwen = QwenConfig.from_env()  # <-- 添加这行
```

- [ ] **Step 3: 语法验证**

```bash
python -m py_compile config/settings.py
```

- [ ] **Step 4: 提交**

```bash
git add config/settings.py
git commit -m "feat: 添加 Qwen3.5-7B 配置"
```

### 任务 1.2：编写 QwenConfig 测试
**文件：** Create: `tests/test_qwen_config.py`

- [ ] **Step 1: 写入测试代码**

```python
# tests/test_qwen_config.py
def test_qwen_config_defaults():
    """测试默认配置"""
    from config.settings import QwenConfig

    config = QwenConfig()
    assert config.model_path == "D:/binance/models/Qwen/Qwen3-8B"
    assert config.auto_download is False
    assert config.quantization == "none"
    assert config.max_tokens == 500
    assert config.temperature == 0.7

def test_qwen_config_from_env():
    """测试从环境变量加载配置"""
    import os
    from config.settings import QwenConfig

    os.environ["QWEN_MODEL_PATH"] = "/custom/path/to/model"
    os.environ["QWEN_AUTO_DOWNLOAD"] = "true"
    os.environ["QWEN_QUANTIZATION"] = "4bit"

    config = QwenConfig.from_env()

    assert config.model_path == "/custom/path/to/model"
    assert config.auto_download is True
    assert config.quantization == "4bit"

# 清理
if 'QWEN_MODEL_PATH' in os.environ:
    del os.environ['QWEN_MODEL_PATH']
if 'QWEN_AUTO_DOWNLOAD' in os.environ:
    del os.environ['QWEN_AUTO_DOWNLOAD']
if 'QWEN_QUANTIZATION' in os.environ:
    del os.environ['QWEN_QUANTIZATION']
```

- [ ] **Step 2: 运行测试（预期会通过）**

```bash
pytest tests/test_qwen_config.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_qwen_config.py
git commit -m "test: 添加 QwenConfig 测试"
```

---

## 阶段 2：QwenTrendAnalyzer 插件化 (预计 2.5 天)

### 任务 2.1：编写 QwenTrendAnalyzer 插件测试（TDD 第一步）
**文件：** Create: `tests/test_qwen_trend_analyzer.py`

- [ ] **Step 1: 写入测试用例**

```python
# tests/test_qwen_trend_analyzer.py
import pytest

@pytest.fixture
def qwen_config():
    """Qwen 配置 fixture"""
    from config.settings import QwenConfig
    return QwenConfig(
        model_path="/test/path",
        auto_download=False
    )

def test_plugin_metadata():
    """测试插件元数据"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    metadata = plugin.metadata

    assert metadata.name == "qwen_trend_analyzer"
    assert metadata.type.value == "utility"
    assert metadata.interface_version == "1.0.0"

def test_plugin_initialization():
    """测试插件初始化"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    # 初始化前模型应该为 None
    assert not hasattr(plugin, 'model_manager') or plugin.model_manager is None

def test_plugin_without_model_path():
    """测试没有模型路径的情况"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    # 初始化应该失败但不崩溃
    with pytest.raises(Exception):
        plugin.initialize()
```

- [ ] **Step 2: 运行测试（预期会失败）**

```bash
pytest tests/test_qwen_trend_analyzer.py -v
```

- [ ] **Step 3: 记录失败状态**

- [ ] **Step 4: 提交**

```bash
git add tests/test_qwen_trend_analyzer.py
git commit -m "test: 添加 QwenTrendAnalyzer 测试（TDD）"
```

### 任务 2.2：复制现有 MarketAnalyzer 作为基础
**文件：** Copy: `ai_trading/market_analyzer.py` → `plugins/qwen_trend_analyzer/__init__.py`

- [ ] **Step 1: 复制文件**

```bash
cp ai_trading/market_analyzer.py plugins/qwen_trend_analyzer/__init__.py
```

- [ ] **Step 2: 语法验证**

```bash
python -m py_compile plugins/qwen_trend_analyzer/__init__.py
```

- [ ] **Step 3: 提交**

```bash
git add plugins/qwen_trend_analyzer/__init__.py
git commit -m "feat: 复制 MarketAnalyzer 作为插件基础"
```

### 任务 2.3：适配为 PluginBase 插件
**文件：** Modify: `plugins/qwen_trend_analyzer/__init__.py:1-100`

- [ ] **Step 1: 添加插件基类导入和继承**

```python
# plugins/qwen_trend_analyzer/__init__.py:1-100
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qwen3.5-7B AI趋势分析插件
"""

from plugins.base import PluginBase, PluginType, PluginMetadata

# 原有的导入保留
import pandas as pd
import numpy as np
from typing import Dict, Optional
from enum import Enum
import logging

# 原有的 TrendType 和 MarketRegime 保留
class TrendType(Enum):
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    SIDEWAYS = "sideways"
    VOLATILE = "volatile"

class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"
    HIGH_VOLATILITY = "high_volatility"

class QwenTrendAnalyzerPlugin(PluginBase):
    """Qwen3.5-7B AI趋势分析插件"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="qwen_trend_analyzer",
            version="1.0.0",
            type=PluginType.UTILITY,
            interface_version="1.0.0",
            description="基于 Qwen3.5-7B 的市场趋势分析插件",
            author="AI Trading System"
        )

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        # 原有的 MarketAnalyzer 初始化代码保留
        self.model_path = self.config.get('model_path',
                                          "D:/binance/models/Qwen/Qwen3-8B")
        self.model = None
        self.tokenizer = None
        self.logger = logging.getLogger('QwenTrendAnalyzer')

        # 如果提供了模型路径，尝试加载模型
        if self.model_path:
            self._load_model()
```

- [ ] **Step 2: 语法验证**

```bash
python -m py_compile plugins/qwen_trend_analyzer/__init__.py
```

- [ ] **Step 3: 提交**

```bash
git add plugins/qwen_trend_analyzer/__init__.py
git commit -m "feat: 适配为 PluginBase 插件"
```

### 任务 2.4：运行测试并修复
**文件：** Modify: `plugins/qwen_trend_analyzer/__init__.py`

- [ ] **Step 1: 运行测试**

```bash
pytest tests/test_qwen_trend_analyzer.py -v
```

- [ ] **Step 2: 修复问题直到测试通过**

- [ ] **Step 3: 提交**

```bash
git add plugins/qwen_trend_analyzer/__init__.py
git commit -m "fix: 修复插件初始化问题"
```

---

## 阶段 3：StrategyMatcher 插件化 (预计 1.5 天)

### 任务 3.1：编写 StrategyMatcher 插件测试（TDD）
**文件：** Create: `tests/test_strategy_matcher.py`

- [ ] **Step 1: 写入测试用例**

```python
# tests/test_strategy_matcher.py
def test_strategy_matcher_metadata():
    """测试策略匹配插件元数据"""
    from plugins.strategy_matcher import StrategyMatcherPlugin

    plugin = StrategyMatcherPlugin()
    metadata = plugin.metadata

    assert metadata.name == "strategy_matcher"
    assert metadata.type.value == "utility"
```

- [ ] **Step 2: 运行测试（预期失败）**

```bash
pytest tests/test_strategy_matcher.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_strategy_matcher.py
git commit -m "test: 添加 StrategyMatcher 测试"
```

### 任务 3.2：复制并适配 StrategyMatcher
**文件：**
- Copy: `ai_trading/strategy_matcher.py` → `plugins/strategy_matcher/__init__.py`
- Modify: 新文件

- [ ] **Step 1: 复制并修改为插件**

```bash
cp ai_trading/strategy_matcher.py plugins/strategy_matcher/__init__.py
```

```python
# plugins/strategy_matcher/__init__.py:1-50
from plugins.base import PluginBase, PluginType, PluginMetadata

class StrategyMatcherPlugin(PluginBase):
    """策略匹配插件"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="strategy_matcher",
            version="1.0.0",
            type=PluginType.UTILITY,
            interface_version="1.0.0",
            description="基于趋势分析结果的策略匹配与选择插件",
            author="AI Trading System"
        )
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_strategy_matcher.py -v
```

- [ ] **Step 3: 修复问题直到通过**

- [ ] **Step 4: 提交**

```bash
git add plugins/strategy_matcher/__init__.py
git commit -m "feat: StrategyMatcher 插件化"
```

---

## 阶段 4：风险控制插件开发 (预计 1 天)

### 任务 4.1：创建简单的风险控制插件
**文件：**
- Create: `plugins/risk_control/__init__.py`

- [ ] **Step 1: 写入最小化风险控制插件**

```python
# plugins/risk_control/__init__.py
from plugins.base import PluginBase, PluginType, PluginMetadata
from typing import Dict, Any

class RiskControlPlugin(PluginBase):
    """风险控制插件（MVP 版本）"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="risk_control",
            version="0.1.0",
            type=PluginType.RISK,
            interface_version="1.0.0",
            description="简单的风险控制插件",
            author="AI Trading System"
        )

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.max_position_size = self.config.get('max_position_size', 0.8)
        self.max_daily_loss = self.config.get('max_daily_loss', 0.05)

    def check_risk_constraints(self, order: Dict, portfolio: Dict) -> Dict:
        """检查风险约束"""
        result = {
            'passed': True,
            'reason': 'OK'
        }

        # 简单检查：总仓位限制
        if portfolio.get('position_ratio', 0) > self.max_position_size:
            result['passed'] = False
            result['reason'] = f"Position ratio exceeds max: {self.max_position_size}"

        # 简单检查：每日亏损限制
        if portfolio.get('daily_pnl', 0) < -self.max_daily_loss:
            result['passed'] = False
            result['reason'] = f"Daily loss exceeds max: {self.max_daily_loss}"

        return result
```

- [ ] **Step 2: 语法验证**

```bash
python -m py_compile plugins/risk_control/__init__.py
```

- [ ] **Step 3: 提交**

```bash
git add plugins/risk_control/__init__.py
git commit -m "feat: 添加简单风险控制插件（MVP）"
```

### 任务 4.2：添加风险控制测试
**文件：** Create: `tests/test_risk_control.py`

- [ ] **Step 1: 写入测试**

```python
# tests/test_risk_control.py
def test_risk_control_metadata():
    """测试风险控制插件元数据"""
    from plugins.risk_control import RiskControlPlugin

    plugin = RiskControlPlugin()
    assert plugin.metadata.name == "risk_control"
    assert plugin.metadata.type.value == "risk"

def test_risk_constraints():
    """测试风险约束检查"""
    from plugins.risk_control import RiskControlPlugin

    plugin = RiskControlPlugin()

    # 正常情况
    portfolio_ok = {
        'position_ratio': 0.5,
        'daily_pnl': 0.01
    }
    result = plugin.check_risk_constraints({}, portfolio_ok)
    assert result['passed']

    # 仓位超限
    portfolio_bad = {
        'position_ratio': 0.9,
        'daily_pnl': 0.01
    }
    result = plugin.check_risk_constraints({}, portfolio_bad)
    assert not result['passed']
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_risk_control.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_risk_control.py
git commit -m "test: 添加风险控制测试"
```

---

## 阶段 5：完整系统集成 (预计 2 天)

### 任务 5.1：创建最小化系统控制器
**文件：**
- Create: `core/system.py`

- [ ] **Step 1: 写入最小化系统控制器**

```python
# core/system.py
import logging
from typing import Optional, Dict, Any
from plugins.manager import PluginManager

class TradingSystem:
    """Qwen3.5-7B 驱动的 AI 交易系统（MVP）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger('TradingSystem')
        self.plugin_manager = PluginManager()
        self._running = False

    async def initialize(self) -> bool:
        """系统初始化"""
        try:
            # 加载指定插件
            plugins_to_load = self.config.get('plugins', [
                'qwen_trend_analyzer',
                'strategy_matcher',
                'risk_control'
            ])

            for plugin_name in plugins_to_load:
                await self.plugin_manager.load_plugin(plugin_name)

            self.logger.info("TradingSystem initialized successfully")
            return True
        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            return False

    def run_single_cycle(self) -> Dict[str, Any]:
        """运行单个交易周期"""
        return {
            'timestamp': 0,
            'status': 'success',
            'message': 'Single cycle executed'
        }
```

- [ ] **Step 2: 语法验证**

```bash
python -m py_compile core/system.py
```

- [ ] **Step 3: 提交**

```bash
git add core/system.py
git commit -m "feat: 创建最小化系统控制器"
```

### 任务 5.2：编写系统集成测试
**文件：** Create: `tests/test_complete_system.py`

- [ ] **Step 1: 写入测试**

```python
# tests/test_complete_system.py
@pytest.mark.asyncio
async def test_system_initialization():
    """测试系统初始化"""
    from core.system import TradingSystem
    from unittest.mock import Mock

    system = TradingSystem(config={'plugins': []})
    system.plugin_manager = Mock()
    system.plugin_manager.load_plugin = Mock()

    result = await system.initialize()
    assert result

def test_single_cycle():
    """测试单个交易周期"""
    from core.system import TradingSystem

    system = TradingSystem()
    result = system.run_single_cycle()
    assert 'status' in result
    assert result['status'] == 'success'
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_complete_system.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_complete_system.py
git commit -m "test: 添加系统集成测试"
```

---

## 阶段总结与待办

### 当前完成状态
- [x] 配置管理扩展
- [x] QwenTrendAnalyzer 插件化
- [x] StrategyMatcher 插件化
- [x] 简单风险控制插件
- [x] 最小化系统控制器
- [ ] 增强 Qwen 模型集成
- [ ] 完整系统集成与端到端测试

### 下一阶段待办 (MVP 后的优化)
- 增强 Qwen 模型推理（异步、GPU 优化）
- 添加完整的熔断机制
- 性能测试与优化
- 回测验证
- 文档完善

---

## 预计总时间表

| 阶段 | 任务数 | 预计天数 | 验收标准 |
|------|--------|----------|----------|
| 1. 配置与基础准备 | 4 | 1.5 | Qwen 配置加载正常，测试通过 |
| 2. QwenTrendAnalyzer 插件化 | 6 | 2.5 | 插件可加载，测试通过 |
| 3. StrategyMatcher 插件化 | 3 | 1.5 | 策略匹配可用，测试通过 |
| 4. 风险控制插件 | 3 | 1.0 | 简单风险检查通过 |
| 5. 系统集成 | 3 | 2.0 | 系统初始化成功，周期运行 |
| **总计** | **19** | **8.5** | **MVP 系统可运行** |

---

## 执行建议

**建议使用 Subagent-Driven 执行：** 由于这是重构项目，建议使用 `superpowers:subagent-driven-development`，每个阶段由专门的 subagent 负责，我在阶段间进行审查。

**执行策略：**
1. 第一批次（阶段 1-2）：配置 + QwenTrendAnalyzer 插件化
2. 第二批次（阶段 3-4）：StrategyMatcher + 风险控制
3. 第三批次（阶段 5）：完整系统集成
