# Qwen3.5-7B 市场趋势判断与策略执行系统设计

## 一、项目概述

本项目是一个基于 Qwen3.5-7B 大语言模型的量化交易系统架构重构，实现了从市场数据获取到策略执行的完整流程。系统旨在通过人工智能增强的趋势判断，结合量化策略匹配，实现智能交易执行。

**重要说明：** 本架构设计遵循项目现有的插件化架构，所有核心模块（MarketAnalyzer、StrategyMatcher、TradingExecutor）均设计为独立插件，继承 PluginBase 基类，实现完整的生命周期管理。

## 二、架构设计

### 2.1 整体架构（插件化）

```
┌─────────────────────────────────────────────────────────────┐
│                  插件化架构核心层                         │
├─────────────────────────────────────────────────────────────┤
│  PluginManager (插件管理器) - 发现、加载、启动、停止插件  │
│  PluginVersionManager (版本管理器) - 语义化版本管理        │
│  RolloutManager (灰度上线管理器) - 多种上线策略          │
│  ReliableEventBus (可靠事件总线) - 事件序列号、重试机制   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    插件实例层（独立插件）                   │
├─────────────────────────────────────────────────────────────┤
│  QwenTrendAnalyzer Plugin (AI趋势分析插件)                  │
│    ├─ 模型加载与管理                                       │
│    ├─ 市场数据分析                                         │
│    ├─ 趋势分类与置信度计算                                 │
│    └─ 结构化输出解析                                       │
│                                                             │
│  StrategyMatcher Plugin (策略匹配插件)                      │
│    ├─ 策略库管理                                           │
│    ├─ 智能匹配算法                                         │
│    ├─ 历史表现统计                                         │
│    └─ 回测验证                                             │
│                                                             │
│  ExecutionEngine Plugin (交易执行插件)                      │
│    ├─ 订单管理器                                           │
│    ├─ 执行器（模拟/实盘）                                   │
│    ├─ 风险控制                                             │
│    └─ 性能监控                                             │
│                                                             │
│  BinanceDataSource Plugin (数据源插件)                      │
│  RiskControl Plugin (风控插件)                             │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    基础设施层                              │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL 数据库（K线、订单、策略历史）                 │
│  内存缓存（Redis）- 实时数据、模型缓存                    │
│  Binance API - 市场数据、实盘交易                          │
│  日志系统 - 结构化日志收集与分析                           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件架构（插件化）

#### 2.2.1 QwenTrendAnalyzer Plugin（AI趋势分析插件）

**类结构（继承 PluginBase）：**
```python
from plugins.base import PluginBase, PluginType, PluginMetadata

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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        # 初始化模型管理器
        self.model_manager = ModelManager(
            model_path=self.config.get('model_path'),
            auto_download=self.config.get('auto_download', True),
            quantization=self.config.get('quantization', 'none')
        )
        # 初始化输入/输出解析器
        self.parser = StructuredIOHandler()
        # 初始化趋势验证器
        self.validator = TrendValidator()

    async def initialize(self) -> bool:
        """插件初始化 - 加载模型"""
        try:
            await self.model_manager.ensure_available()
            self._initialized = True
            return True
        except Exception as e:
            self.logger.error(f"Plugin initialization failed: {e}")
            return False

    async def analyze_trend(self, market_data: pd.DataFrame) -> TrendAnalysisResult:
        """
        分析市场趋势（插件主方法）

        Args:
            market_data: K线数据 DataFrame

        Returns:
            TrendAnalysisResult - 趋势分析结果
        """
        if not self._initialized:
            raise RuntimeError("Plugin not initialized")

        # 1. 市场数据特征提取
        features = self._extract_features(market_data)

        # 2. 调用 Qwen 模型推理
        prompt = self.parser.build_prompt(features)
        model_output = await self.model_manager.generate(
            prompt,
            max_tokens=500,
            temperature=0.7
        )

        # 3. 解析结构化输出
        parsed = self.parser.parse_output(model_output)

        # 4. 趋势验证与置信度计算
        confidence = self.validator.validate_and_calculate_confidence(
            parsed,
            market_data,
            features
        )

        # 5. 通过事件总线广播结果
        await self._publish_analysis_result(parsed, confidence)

        return TrendAnalysisResult(
            trend_type=parsed.trend,
            confidence=confidence,
            analysis_text=model_output,
            suggested_strategies=parsed.suggested_strategies,
            features=features
        )

    def health_check(self) -> PluginHealthStatus:
        """插件健康检查"""
        return self.model_manager.get_health_status()
```

**核心子模块：**

**ModelManager（模型管理器）：**
```python
class ModelManager:
    """Qwen3.5-7B 模型管理器 - 负责加载、验证、更新"""

    async def ensure_available(self) -> str:
        """确保模型可用，自动下载和验证"""
        if not self._is_model_present():
            await self._download_model()
        await self._verify_model()
        await self._load_model()
        return self.model_path

    async def _download_model(self):
        """下载模型（支持断点续传）"""
        downloader = ModelDownloader()
        await downloader.download(
            url=self.config.get('model_url'),
            target_path=self.model_path,
            verify_hash=self.config.get('model_hash')
        )

    async def generate(self, prompt: str, **kwargs) -> str:
        """异步模型推理"""
        # 支持 GPU/CPU 自动切换
        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs = inputs.to(self.device)

        with torch.no_grad(), torch.cuda.amp.autocast():
            outputs = self.model.generate(**inputs, **kwargs)

        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)
```

**关键生命周期：**
- `initialize()`: 插件初始化，加载模型
- `start()`: 插件启动，订阅事件
- `analyze_trend()`: 核心业务方法
- `health_check()`: 健康检查
- `stop()`: 插件停止
- `shutdown()`: 插件关闭，释放资源

#### 2.2.2 StrategyMatcher Plugin（策略匹配插件）

**类结构（继承 PluginBase）：**
```python
class StrategyMatcherPlugin(PluginBase):
    """策略匹配与选择插件"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="strategy_matcher",
            version="1.0.0",
            type=PluginType.UTILITY,
            interface_version="1.0.0",
            description="基于趋势分析结果的策略匹配与选择插件",
            author="AI Trading System"
        )

    async def initialize(self) -> bool:
        """插件初始化"""
        self.strategy_registry = StrategyRegistry()
        self.match_algorithm = SmartMatchingEngine()
        self.performance_tracker = PerformanceAnalytics()
        return True

    async def match_strategies(self, trend_analysis: TrendAnalysisResult) -> List[StrategyRecommendation]:
        """
        根据趋势分析结果匹配策略

        Args:
            trend_analysis: 趋势分析结果

        Returns:
            List[StrategyRecommendation] - 按优先级排序的策略推荐
        """
        # 1. 加载可应用策略
        available_strategies = await self._get_available_strategies()

        # 2. 智能匹配算法
        matched = await self.match_algorithm.match(
            available_strategies,
            trend_analysis,
            context={
                'market_conditions': await self._get_market_context(),
                'portfolio_status': await self._get_portfolio_status()
            }
        )

        # 3. 历史表现评分
        scored = await self.performance_tracker.score_strategies(
            matched,
            trend_analysis
        )

        # 4. 风险调整与排序
        final_recommendations = await self._rank_and_recommend(scored, trend_analysis)

        return final_recommendations

    def health_check(self) -> PluginHealthStatus:
        """健康检查"""
        return self.performance_tracker.health_check()
```

**智能匹配算法：**
```python
class SmartMatchingEngine:
    """基于机器学习的智能策略匹配"""

    async def match(self, strategies, trend_analysis, context) -> List[Strategy]:
        scores = []

        for strategy in strategies:
            # 基础匹配分数
            base_score = self._calculate_base_score(strategy, trend_analysis)

            # 上下文感知分数调整
            context_score = await self._adjust_for_context(strategy, context)

            # 历史表现权重
            performance_score = await self._get_performance_weight(strategy)

            total_score = base_score * 0.6 + context_score * 0.2 + performance_score * 0.2

            if total_score > 0.5:  # 最小匹配阈值
                scores.append((total_score, strategy))

        return [strategy for score, strategy in sorted(scores, key=lambda x: -x[0])]

    def _calculate_base_score(self, strategy, analysis):
        """计算基础匹配分数"""
        trend_match = 1.0 if analysis.trend in strategy.suitable_trends else 0.0
        volatility_match = 1.0 if analysis.volatility <= strategy.max_volatility else 0.0

        return (trend_match * 0.7 + volatility_match * 0.3) * analysis.confidence
```

            # 置信度匹配（20% 权重）
            if strategy.min_confidence <= confidence:
                score += 0.2

            # 历史表现（20% 权重）
            score += strategy.historical_performance * 0.2

            if score > 0.5:
                strategy.match_score = score
                matched.append(strategy)

        return matched
```

#### 2.2.3 交易执行器 (TradingExecutor)

**类结构：**
```python
class TradingExecutor:
    def __init__(self, is_paper_trading: bool = True):
        self.order_manager = OrderManager()
        self.risk_manager = RiskManager()
        self.execution_handler = PaperTradingHandler() if is_paper_trading \
            else BinanceExecutionHandler()
        self.performance_tracker = PerformanceTracker()

    def execute_strategy(self, strategy: Strategy, trend_analysis: TrendAnalysisResult) -> ExecutionResult:
        # 1. 风险评估
        risk_check = self.risk_manager.evaluate_risk(strategy, trend_analysis)
        if not risk_check.passed:
            return ExecutionResult.failed(risk_check.reason)

        # 2. 计算仓位大小
        position_size = self._calculate_position_size(strategy, trend_analysis)
        if position_size <= 0:
            return ExecutionResult.failed("Insufficient capital or risk constraints")

        # 3. 执行订单
        order = self.order_manager.create_order(
            symbol=strategy.symbol,
            side=strategy.side,
            quantity=position_size,
            strategy=strategy.name
        )

        execution_result = self.execution_handler.execute(order)

        # 4. 性能追踪
        self.performance_tracker.track_order(execution_result)

        return execution_result
```

**执行流程：**
```
创建订单 → 风险评估 → 执行订单 → 确认成交 → 记录日志 → 更新绩效
```

## 三、Qwen3.5-7B 部署设计

### 3.1 模型加载与推理

**架构：**
```python
class ModelLoader:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True
            )

            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                device_map="auto"
            )

            logger.info("Qwen3.5-7B 模型加载成功")
        except Exception as e:
            logger.error(f"Qwen3.5-7B 模型加载失败: {e}")
            self.model = None
            self.tokenizer = None

    def inference(self, prompt: str, max_tokens: int = 500) -> str:
        if self.model is None or self.tokenizer is None:
            raise Exception("Qwen3.5-7B 模型未加载")

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            temperature=0.7,
            do_sample=True
        )

        return self.tokenizer.decode(outputs[0], skip_special_tokens=True)
```

### 3.2 结构化输入/输出解析

**输入解析：**
```python
class InputParser:
    @staticmethod
    def prepare_market_analysis_input(market_data: pd.DataFrame) -> str:
        # 价格统计
        price_summary = {
            'current_price': market_data['close'].iloc[-1],
            'price_change_24h': (market_data['close'].iloc[-1] - market_data['close'].iloc[-24]) /
                             market_data['close'].iloc[-24] * 100,
            'price_change_7d': (market_data['close'].iloc[-1] - market_data['close'].iloc[-168]) /
                             market_data['close'].iloc[-168] * 100,
            'high_24h': market_data['high'][-24:].max(),
            'low_24h': market_data['low'][-24:].min()
        }

        # 波动率计算
        returns = np.diff(np.log(market_data['close']))
        volatility = returns[-20:].std() * np.sqrt(365)

        # 成交量分析
        volume_summary = {
            'avg_volume_24h': market_data['volume'][-24:].mean(),
            'volume_trend': market_data['volume'][-5:].mean() /
                          market_data['volume'][-20:].mean()
        }

        return f"""
你是一个专业的加密货币市场分析师。请分析以下 BTCUSDT 市场数据并提供详细分析。

=== 价格统计 ===
当前价格: ${price_summary['current_price']:.2f}
24小时涨跌幅: {price_summary['price_change_24h']:.2f}%
7天涨跌幅: {price_summary['price_change_7d']:.2f}%
24小时最高: ${price_summary['high_24h']:.2f}
24小时最低: ${price_summary['low_24h']:.2f}

=== 市场波动率 ===
20期波动率: {volatility:.2%}

=== 成交量分析 ===
24小时平均成交量: {volume_summary['avg_volume_24h']:.0f}
成交量趋势: {volume_summary['volume_trend']:.2f} (近5期/近20期)

请提供以下信息：
1. 趋势判断：上涨/下跌/震荡
2. 置信度：0.0 - 1.0 的数值
3. 风险评估：低/中/高
4. 支持/阻力位分析
5. 操作建议
6. 适合的交易策略类型（趋势跟踪/均值回归/高波动）
"""
```

**输出解析：**
```python
class OutputParser:
    @staticmethod
    def parse_market_analysis(text: str) -> AnalysisResult:
        # 使用正则表达式提取结构化信息
        # 实际项目中可能使用更复杂的 NLP 解析

        trend_match = re.search(r'趋势判断：(上涨|下跌|震荡)', text)
        trend = TrendType.UPTREND if trend_match.group(1) == '上涨' else \
               TrendType.DOWNTREND if trend_match.group(1) == '下跌' else \
               TrendType.SIDEWAYS

        confidence_match = re.search(r'置信度：([0-9.]+)', text)
        confidence = float(confidence_match.group(1))

        return AnalysisResult(
            trend=trend,
            confidence=confidence,
            raw_text=text
        )
```

## 四、数据流程设计

```
市场数据获取 (Binance API)
    ↓
数据清洗与格式化
    ↓
┌───────────────────────┐
│ 特征工程 (历史数据)     │
│  ├─ 价格序列特征         │
│  ├─ 成交量特征           │
│  ├─ 波动率特征           │
│  └─ 技术指标             │
└──────────────┬──────────┘
               │
               ├───────────┬───────────┐
               │           │           │
┌──────────────▼──┐ ┌──────▼──────┐ ┌▼────────────┐
│ Qwen3.5-7B 推理 │ │ 统计分析    │ │ 技术指标计算 │
└──────────────┬──┘ └──────┬──────┘ └───────┬──────┘
               │           │               │
               └───────────┼───────────────┘
                         │
                    趋势判断
                         │
                    策略匹配
                         │
                    交易执行
                         │
                    结果存储
```

## 五、风险控制设计

### 5.1 风险层次

**一级风险（系统级）：**
- 最大仓位限制（总仓位 ≤ 80%）
- 单笔仓位限制（单笔 ≤ 20%）
- 每日亏损限制（≤ 5%）

**二级风险（策略级）：**
- 策略止损止盈
- 策略最大亏损限制

**三级风险（执行级）：**
- 价格滑点控制
- 订单执行监控
- 网络异常处理

### 5.2 三级熔断机制

```python
class CircuitBreaker:
    """三级熔断机制 - 警告 → 暂停 → 停止"""

    class Level(Enum):
        NORMAL = "normal"
        WARNING = "warning"
        PAUSED = "paused"
        STOPPED = "stopped"

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._level = self.Level.NORMAL
        self._warning_threshold = config.warning_threshold
        self._pause_threshold = config.pause_threshold
        self._stop_threshold = config.stop_threshold
        self._last_trigger_time = None
        self._persistence_store = PersistenceStore()

    async def check_circuit_state(self, metrics: RiskMetrics) -> CircuitState:
        """检查熔断状态"""
        new_level = self._calculate_level(metrics)

        if new_level != self._level:
            await self._transition_state(new_level, metrics)

        return CircuitState(
            level=self._level,
            message=self._get_status_message(),
            can_trade=self._level == self.Level.NORMAL
        )

    def _calculate_level(self, metrics: RiskMetrics) -> CircuitBreaker.Level:
        """计算当前熔断级别"""
        # 综合风险指标
        risk_score = self._calculate_risk_score(metrics)

        if risk_score >= self._stop_threshold:
            return self.Level.STOPPED
        elif risk_score >= self._pause_threshold:
            return self.Level.PAUSED
        elif risk_score >= self._warning_threshold:
            return self.Level.WARNING

        return self.Level.NORMAL

    async def _transition_state(self, new_level: Level, metrics: RiskMetrics):
        """状态转换处理"""
        self.logger.warning(f"Circuit breaker state changed: {self._level} -> {new_level}")

        self._level = new_level
        self._last_trigger_time = datetime.now()

        # 持久化状态
        await self._persistence_store.save_circuit_state(
            self._level,
            self._last_trigger_time
        )

        # 发布状态变更事件
        await self._event_bus.publish(
            "circuit_breaker.state_changed",
            {
                "old_state": old_level,
                "new_state": new_level,
                "metrics": metrics,
                "timestamp": datetime.now()
            }
        )

    async def reset(self):
        """重置熔断状态（手动恢复）"""
        if self._level == self.Level.STOPPED:
            # 需要人工确认才能从 STOPPED 恢复
            raise CircuitBreakerRecoveryError(
                "Cannot auto-recover from STOPPED state. "
                "Manual intervention required."
            )

        self._level = self.Level.NORMAL
        self._last_trigger_time = None
        await self._persistence_store.clear_circuit_state()

    def _calculate_risk_score(self, metrics: RiskMetrics) -> float:
        """计算综合风险评分"""
        score = 0.0

        # 亏损贡献（40%）
        loss_contribution = metrics.daily_loss / self.config.max_daily_loss
        score += min(loss_contribution * 0.4, 1.0)

        # 仓位贡献（30%）
        position_contribution = metrics.total_position / self.config.max_position
        score += min(position_contribution * 0.3, 1.0)

        # 回撤贡献（30%）
        drawdown_contribution = metrics.current_drawdown / self.config.max_drawdown
        score += min(drawdown_contribution * 0.3, 1.0)

        return score
```

### 5.3 量化风险评估

```python
class QuantitativeRiskAssessor:
    """量化风险评估器"""

    def assess_strategy_risk(self, strategy: Strategy,
                             market_conditions: MarketConditions) -> RiskAssessment:
        """量化评估策略风险"""
        # 1. 计算历史最大回撤
        max_drawdown = await self._calculate_max_drawdown(strategy)

        # 2. 计算夏普比率
        sharpe_ratio = await self._calculate_sharpe_ratio(strategy)

        # 3. 计算VaR（风险价值）
        var_95 = await self._calculate_var(strategy, confidence=0.95)

        # 4. 综合风险评分
        risk_score = self._synthesize_risk_score(
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            var_95=var_95
        )

        # 5. 风险等级判断
        risk_level = self._determine_risk_level(risk_score)

        return RiskAssessment(
            score=risk_score,
            level=risk_level,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            var_95=var_95
        )

    def _synthesize_risk_score(self, **metrics) -> float:
        """综合风险评分计算"""
        max_drawdown = metrics['max_drawdown']
        sharpe_ratio = metrics['sharpe_ratio']

        # 归一化处理
        drawdown_score = min(max_drawdown / 0.5, 1.0)  # 50% 最大回撤
        sharpe_score = max(1 - sharpe_ratio / 2.0, 0)  # Sharpe >= 2.0 为好

        # 加权综合
        risk_score = (drawdown_score * 0.6) + (sharpe_score * 0.4)

        return min(risk_score, 1.0)
```

### 5.4 风险管理架构

```python
class RiskControlPlugin(PluginBase):
    """风险控制插件"""

    def _get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="risk_control",
            version="1.0.0",
            type=PluginType.RISK,
            interface_version="1.0.0",
            description="综合风险控制与熔断插件"
        )

    async def initialize(self):
        self.circuit_breaker = CircuitBreaker(self.config.circuit_breaker)
        self.quantitative_assessor = QuantitativeRiskAssessor()
        self.risk_event_logger = RiskEventLogger()
        self._load_state()

    async def check_risk_constraints(self, order: Order, market_data) -> RiskCheckResult:
        """检查风险约束"""
        result = RiskCheckResult(passed=True)

        # 1. 检查熔断状态
        circuit_state = await self.circuit_breaker.check_circuit_state()
        if not circuit_state.can_trade:
            return RiskCheckResult(
                passed=False,
                reason=f"Circuit breaker active: {circuit_state.level}",
                level=RiskLevel.CRITICAL
            )

        # 2. 量化风险评估
        risk_assessment = await self.quantitative_assessor.assess_strategy_risk(
            strategy, market_data
        )

        if risk_assessment.level >= RiskLevel.HIGH:
            return RiskCheckResult(
                passed=False,
                reason=f"High risk detected: {risk_assessment.score:.2f}",
                level=risk_assessment.level
            )

        # 3. 仓位限制检查
        if not await self._check_position_limits(order):
            return RiskCheckResult(
                passed=False,
                reason="Position limits exceeded",
                level=RiskLevel.MEDIUM
            )

        # 4. 记录风险检查
        await self.risk_event_logger.log_check(result)

        return result
```

## 六、部署架构

### 6.1 硬件需求

| 组件 | 最小配置 | 推荐配置 |
|------|----------|----------|
| CPU | Intel i5-8400 | Intel i9-12900K 或 AMD Ryzen 9 5950X |
| GPU | NVIDIA GTX 1660 Ti (6GB) | NVIDIA RTX 3090 (24GB) 或 A100 (40GB) |
| 内存 | 16GB DDR4 | 32GB DDR4 或 64GB DDR5 |
| 存储 | 500GB SSD | 2TB NVMe SSD |

### 6.2 软件架构

```
操作系统: Windows 10/11 或 Ubuntu 20.04+
├── Python 3.9+ (系统核心层)
│   ├── transformers (Qwen3.5-7B)
│   ├── pandas/numpy (数据处理)
│   ├── torch (PyTorch)
│   ├── scikit-learn (机器学习)
│   └── psycopg2 (PostgreSQL)
├── Node.js 16+ (数据获取、API 服务)
│   ├── @binance/connector (Binance SDK)
│   └── pg (PostgreSQL 连接)
├── PostgreSQL 13+
└── Git (版本控制)
```

### 6.3 目录结构

```
D:/binance/
├── config/                    # 配置文件
├── core/                      # 核心模块
│   ├── market_analyzer.py
│   ├── strategy_matcher.py
│   └── trading_executor.py
├── data/                      # 数据存储
│   ├── historical/            # 历史数据
│   └── realtime/              # 实时数据
├── models/                    # AI 模型
│   └── Qwen/                  # Qwen3.5-7B
├── strategy/                  # 策略库
│   ├── __init__.py
│   ├── base.py
│   ├── dual_ma.py
│   └── rsi_strategy.py
├── trading/                   # 交易执行
│   ├── __init__.py
│   ├── order.py
│   └── execution.py
├── risk/                      # 风险管理
│   ├── __init__.py
│   └── manager.py
├── utils/                     # 工具函数
│   ├── __init__.py
│   ├── helpers.py
│   ├── logger.py
│   └── database.py
├── docs/                      # 文档
├── tests/                     # 测试
├── main.py                    # 系统入口
└── requirements.txt           # Python 依赖
```

## 七、测试与验证策略（优化后）

### 7.1 单元测试

```python
# 市场分析模块测试
@pytest.mark.asyncio
async def test_qwen_trend_analyzer():
    # 使用测试配置初始化插件
    config = {
        'model_path': "D:/binance/models/Qwen3.5-7B",
        'auto_download': False,
        'quantization': 'none'
    }
    analyzer = QwenTrendAnalyzerPlugin(config)
    await analyzer.initialize()

    # 使用模拟数据测试
    df = generate_realistic_test_data()

    # 测试分析功能
    result = await analyzer.analyze_trend(df)

    assert result.trend in [TrendType.UPTREND, TrendType.DOWNTREND, TrendType.SIDEWAYS]
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.suggested_strategies) > 0

# 策略匹配模块测试
@pytest.mark.asyncio
async def test_strategy_matcher():
    matcher = StrategyMatcherPlugin()
    await matcher.initialize()

    analysis = TrendAnalysisResult(
        trend=TrendType.UPTREND,
        confidence=0.8,
        volatility=0.03,
        volume_trend=1.2
    )

    strategies = await matcher.match_strategies(analysis)

    assert len(strategies) > 0

    # 检查是否返回适合趋势的策略
    for strategy in strategies:
        assert TrendType.UPTREND in strategy.suitable_trends
        assert strategy.confidence >= 0.5

# 风险控制模块测试
@pytest.mark.asyncio
async def test_risk_control():
    risk_control = RiskControlPlugin()
    await risk_control.initialize()

    order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        quantity=1.0,
        price=45000
    )

    market_data = generate_market_snapshot()

    # 测试正常市场条件
    result = await risk_control.check_risk_constraints(order, market_data)
    assert result.passed

# 熔断机制测试
@pytest.mark.asyncio
async def test_circuit_breaker():
    breaker = CircuitBreaker(config=CircuitBreakerConfig())

    # 测试正常状态
    metrics = RiskMetrics(daily_loss=0.01, total_position=0.1, drawdown=0.02)
    state = await breaker.check_circuit_state(metrics)
    assert state.can_trade

    # 测试警告状态
    metrics = RiskMetrics(daily_loss=0.03, total_position=0.4, drawdown=0.08)
    state = await breaker.check_circuit_state(metrics)
    assert state.level == CircuitBreaker.Level.WARNING

    # 测试暂停状态
    metrics = RiskMetrics(daily_loss=0.06, total_position=0.6, drawdown=0.12)
    state = await breaker.check_circuit_state(metrics)
    assert state.level == CircuitBreaker.Level.PAUSED

    # 测试停止状态
    metrics = RiskMetrics(daily_loss=0.15, total_position=0.9, drawdown=0.25)
    state = await breaker.check_circuit_state(metrics)
    assert state.level == CircuitBreaker.Level.STOPPED
```

### 7.2 集成测试

**完整交易周期测试：**
```python
@pytest.mark.asyncio
async def test_complete_trading_cycle():
    # 初始化系统（使用内存存储和模拟接口）
    from core.system import TradingSystem

    system = TradingSystem(
        config={
            'paper_trading': True,
            'initial_capital': 10000,
            'plugins': [
                'qwen_trend_analyzer',
                'strategy_matcher',
                'risk_control',
                'execution_engine'
            ]
        }
    )

    await system.initialize()

    # 运行一个完整周期
    result = await system.run_single_cycle()

    # 验证结果
    assert result['status'] in ['success', 'failed']
    assert 'trend_analysis' in result

    if result['status'] == 'success':
        assert 'strategy' in result
        assert 'order' in result
```

### 7.3 性能测试

```python
@pytest.mark.performance
@pytest.mark.asyncio
async def test_inference_performance():
    """测试模型推理性能"""
    analyzer = QwenTrendAnalyzerPlugin()
    await analyzer.initialize()

    test_data = generate_performance_test_data()

    start_time = time.time()
    results = []

    for i in range(20):
        result = await analyzer.analyze_trend(test_data)
        results.append(result)
        await asyncio.sleep(0.1)

    avg_time = (time.time() - start_time) / 20

    # 性能指标验证
    assert avg_time < 2.0  # 单次推理小于 2 秒
    assert len([r for r in results if r.confidence > 0.7]) > 15  # 高置信度结果占比 > 75%

@pytest.mark.performance
@pytest.mark.asyncio
async def test_strategy_matching_speed():
    """测试策略匹配性能"""
    matcher = StrategyMatcherPlugin()
    await matcher.initialize()

    analysis = TrendAnalysisResult(
        trend=TrendType.UPTREND,
        confidence=0.8,
        volatility=0.03,
        volume_trend=1.2
    )

    start_time = time.time()
    recommendations = await matcher.match_strategies(analysis)
    match_time = time.time() - start_time

    assert match_time < 0.5  # 策略匹配时间小于 0.5 秒
    assert len(recommendations) > 0
    assert recommendations[0].confidence >= recommendations[1].confidence  # 按分数排序
```

### 7.4 回测验证

```python
@pytest.mark.backtest
@pytest.mark.asyncio
async def test_strategy_backtest():
    """测试策略回测性能"""
    from backtest.engine import BacktestEngine

    # 使用 BTCUSDT 历史数据（2024年1月-2月）
    backtest_data = load_backtest_data("BTCUSDT", "1h", "2024-01-01", "2024-02-01")

    # 创建回测引擎
    engine = BacktestEngine(
        initial_capital=10000,
        commission_rate=0.001,
        slippage=0.001
    )

    # 设置策略和分析器
    engine.add_strategy(await create_trend_following_strategy())
    engine.add_analyzer(await create_performance_analyzer())

    # 运行回测
    results = await engine.run(backtest_data)

    # 验证回测结果
    assert 'total_return' in results
    assert 'sharpe_ratio' in results
    assert 'max_drawdown' in results

    print(f"回测结果:")
    print(f"总收益率: {results['total_return']:.2%}")
    print(f"夏普比率: {results['sharpe_ratio']:.2f}")
    print(f"最大回撤: {results['max_drawdown']:.2%}")
    print(f"交易次数: {results['total_trades']}")

    # 验证策略是否在亏损情况下停止
    assert results['max_drawdown'] < 0.25  # 最大回撤小于 25%

    # 验证夏普比率为正
    assert results['sharpe_ratio'] > 0.0

    return results
```

### 7.5 稳定性测试

```python
@pytest.mark.stability
@pytest.mark.asyncio
async def test_long_running_stability():
    """长时间运行稳定性测试"""
    system = TradingSystem(config={
        'paper_trading': True,
        'run_duration': 3600,  # 1小时
        'cycle_interval': 300  # 5分钟周期
    })

    await system.initialize()

    start_time = time.time()

    try:
        await system.run()
    except Exception as e:
        pytest.fail(f"系统运行时异常: {e}")

    run_time = time.time() - start_time

    # 验证运行时间接近预期
    assert 3500 < run_time < 3700
```

### 7.6 测试框架和工具

```python
# 测试配置（conftest.py）
def pytest_configure(config):
    # 添加自定义标记
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "backtest: mark test as backtest test"
    )
    config.addinivalue_line(
        "markers", "stability: mark test as stability test"
    )

# 测试运行配置
def run_tests():
    """运行所有测试"""
    import subprocess

    # 运行快速测试（排除性能和回测）
    result = subprocess.run([
        "pytest", "tests/", "-v",
        "-m", "not performance and not backtest and not stability"
    ])

    if result.returncode != 0:
        return result.returncode

    # 运行性能测试
    result = subprocess.run([
        "pytest", "tests/", "-v", "-m", "performance"
    ])

    if result.returncode != 0:
        return result.returncode

    # 运行回测
    result = subprocess.run([
        "pytest", "tests/", "-v", "-m", "backtest"
    ])

    return result.returncode
```

## 八、性能优化策略

### 8.1 模型推理优化

**GPU 加速：**
```python
class ModelOptimizer:
    @staticmethod
    def optimize_model(model, dtype: str = "float16"):
        # 使用半精度推理
        if dtype == "float16":
            model.half()

        # 启用 CUDA 图优化（如果支持）
        if torch.cuda.is_available():
            model = torch.compile(model)

        return model
```

**批量推理：**
```python
class BatchInference:
    def __init__(self, model, tokenizer, max_batch_size: int = 8):
        self.model = model
        self.tokenizer = tokenizer
        self.max_batch_size = max_batch_size

    def process_batch(self, prompts: List[str]) -> List[str]:
        inputs = self.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=2048
        ).to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=500,
                temperature=0.7
            )

        return [
            self.tokenizer.decode(output, skip_special_tokens=True)
            for output in outputs
        ]
```

### 8.2 数据处理优化

**缓存策略：**
```python
class DataCache:
    def __init__(self, ttl: int = 600):
        self.cache = {}
        self.ttl = ttl

    def get_cached_data(self, symbol: str, interval: str, lookback: int) -> Optional[pd.DataFrame]:
        key = f"{symbol}_{interval}_{lookback}"

        if key in self.cache:
            timestamp, data = self.cache[key]

            if time.time() - timestamp < self.ttl:
                return data

        return None

    def cache_data(self, symbol: str, interval: str,
                   lookback: int, data: pd.DataFrame):
        key = f"{symbol}_{interval}_{lookback}"

        self.cache[key] = (time.time(), data.copy())

        # 清理过期缓存
        self._cleanup()

    def _cleanup(self):
        now = time.time()
        keys_to_delete = [
            key for key, (ts, _) in self.cache.items()
            if now - ts > self.ttl
        ]

        for key in keys_to_delete:
            del self.cache[key]
```

## 九、监控与运维

### 9.1 系统监控

```python
class SystemMonitor:
    def __init__(self):
        self.metrics = {
            'cpu_usage': 0.0,
            'memory_usage': 0.0,
            'gpu_memory_usage': 0.0,
            'inference_time': 0.0,
            'throughput': 0
        }

        self.logger = Logger.get_instance()

    def record_inference_time(self, duration: float):
        self.metrics['inference_time'] = duration

    def check_system_health(self) -> bool:
        # 检查核心组件健康状态
        if not self._check_database_connection():
            return False

        if not self._check_api_response():
            return False

        if self._check_resources_exhaustion():
            return False

        return True
```

### 9.2 日志系统

**架构：**
```
┌─────────────────────────┐
│  应用程序日志            │
│  ├─ info (运行信息)     │
│  ├─ debug (调试信息)    │
│  ├─ warning (警告)      │
│  └─ error (错误)        │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│  文件存储                │
│  ├─ daily log files    │
│  └─ rolling log files  │
└────────────┬────────────┘
             │
┌────────────▼────────────┐
│  监控系统 (预留)         │
│  ├─ Prometheus         │
│  └─ Grafana            │
└─────────────────────────┘
```

## 十、实施计划

### 阶段 1：基础架构 (预计 2 周)

- [ ] 创建项目骨架与配置文件
- [ ] 实现 Qwen3.5-7B 模型加载器
- [ ] 创建基础数据获取模块
- [ ] 设置 PostgreSQL 数据库

### 阶段 2：核心模块开发 (预计 3 周)

- [ ] 实现市场分析模块
- [ ] 实现策略匹配模块
- [ ] 实现交易执行模块
- [ ] 集成风险管理

### 阶段 3：Qwen3.5-7B 集成 (预计 2 周)

- [ ] 优化模型推理性能
- [ ] 开发输入/输出解析器
- [ ] 实现趋势判断功能
- [ ] 集成到系统中

### 阶段 4：测试与优化 (预计 2 周)

- [ ] 编写单元测试
- [ ] 运行集成测试
- [ ] 性能优化
- [ ] 修复 bug

### 阶段 5：部署与验证 (预计 1 周)

- [ ] 配置生产环境
- [ ] 性能基准测试
- [ ] 安全性检查
- [ ] 文档完善

## 十一、风险与缓解策略

### 11.1 技术风险

**风险 1：Qwen3.5-7B 模型加载失败**
- **症状**：模型无法加载到内存，或加载时间过长
- **缓解**：
  - 提供模型下载脚本和验证工具
  - 优化模型权重格式（使用 `safetensors`）
  - 提供降级方案（使用基于规则的分析）

**风险 2：模型推理时间过长**
- **症状**：单次推理超过 10 秒
- **缓解**：
  - 优化 CUDA 内存使用
  - 启用模型量化（4-bit 量化）
  - 使用批处理推理

**风险 3：市场分析结果不稳定**
- **症状**：Qwen3.5-7B 的趋势判断不一致
- **缓解**：
  - 使用基于规则的分析作为验证
  - 训练模型时增加市场数据多样性
  - 实现多模型投票机制

### 11.2 业务风险

**风险 4：策略匹配不准确**
- **症状**：匹配的策略表现不佳
- **缓解**：
  - 持续更新策略库和匹配算法
  - 实现策略回测和验证机制
  - 提供策略手动选择功能

**风险 5：实盘交易失败**
- **症状**：Binance API 请求超时或拒绝
- **缓解**：
  - 实现重试和容错机制
  - 使用模拟交易模式验证
  - 实施严格的风险管理

**风险 6：数据质量问题**
- **症状**：市场数据不完整或不准确
- **缓解**：
  - 实现数据清洗和验证
  - 使用多个数据源交叉验证
  - 提供数据修复工具

## 十二、总结

本设计提供了一个完整的、基于 Qwen3.5-7B 的量化交易系统架构，涵盖了从市场分析到策略执行的所有环节。系统采用分层架构设计，各模块职责清晰，易于扩展和维护。

**主要亮点：**

1. **Qwen3.5-7B 深度集成**：作为核心分析引擎，提供高级市场洞察力
2. **策略匹配优化**：基于历史表现和置信度评分的智能策略选择
3. **风险控制**：多层次风险管理，支持模拟交易和实盘操作
4. **性能优化**：GPU 加速推理、内存管理和批量处理
5. **可扩展性**：模块化设计支持功能增量开发和集成
6. **安全可靠性**：全面的测试、监控和运维支持

**预期成果：**
- 实现完全重构现有架构的目标
- 支持多种策略类型和风险偏好
- 提供可验证的绩效指标
- 具备生产环境部署能力
