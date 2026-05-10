package com.trading.execution.v3;

import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.pool.ChanExpert;
import com.trading.adapter.pool.AIExpert;
import com.trading.adapter.risk.RiskManagerV2;
import com.trading.adapter.shadow.ChampionChallengerManager;
import com.trading.domain.signal.*;
import com.trading.domain.strategy.TradingStrategy;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.VolatilityRegime;
import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.execution.v2.*;
import plugin.PluginHotSwapEngine;
import selector.StrategySelector;
import state.ChanMarketState;
import chan.ChanPricePoint;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * ExecutionEngine V3 - 融合V2 + 演化交易功能
 *
 * @deprecated 保留作为参考 - 使用 com.trading.adapter.execution.ExecutionEngine 替代
 * V3版本遗留代码,不再维护
 *
 * V3 = V2 + StrategyRouter + ChampionChallenger + PluginHotSwap
 */
@Deprecated
public class ExecutionEngineV3 {

    // V2 核心组件
    private final ExecutionStateMachineV2 stateMachine;
    private final OrderManager orderManager;
    private final SmartRouterV2 router;
    private final RiskGate riskGate;
    private final PositionManager positionManager;
    private final BinanceAdapterV2 adapter;

    // V3 新增组件
    private final StrategyRouter strategyRouter;
    private final Map<AlphaType, TradingStrategy> strategies;
    private final ChampionChallengerManager championManager;
    private final PluginHotSwapEngine pluginEngine;
    private final StrategySelector strategySelector;
    private final MarketTrendDetector trendDetector;

    // 统计
    private final AtomicInteger totalSignals = new AtomicInteger(0);
    private final AtomicInteger totalOrders = new AtomicInteger(0);
    private final AtomicInteger riskRejects = new AtomicInteger(0);
    private final AtomicInteger strategyChanges = new AtomicInteger(0);

    private AlphaType lastActiveStrategy = null;

    public ExecutionEngineV3(RiskManagerV2 riskManager, BinanceAdapterV2 adapter,
                              MetaLearner metaLearner, ChanExpert chanExpert, String symbol) {
        // 初始化V2组件
        this.adapter = adapter;
        this.stateMachine = new ExecutionStateMachineV2(riskManager);
        this.router = new SmartRouterV2(symbol);
        this.riskGate = new RiskGate(riskManager);
        this.positionManager = new PositionManager();
        this.orderManager = new OrderManager(adapter, positionManager::onFill);

        // 初始化V3组件
        this.strategyRouter = new StrategyRouter();
        this.strategies = new ConcurrentHashMap<>();

        // 注册内置策略
        strategies.put(AlphaType.MEAN_REVERSION, new com.trading.execution.v3.strategies.MeanReversionStrategy());
        strategies.put(AlphaType.TREND_FOLLOWING, new com.trading.execution.v3.strategies.TrendFollowingStrategy());
        strategies.put(AlphaType.VOLATILITY, new com.trading.execution.v3.strategies.VolatilityStrategy());

        // 初始化演化组件
        this.strategySelector = new StrategySelector();
        this.pluginEngine = new PluginHotSwapEngine(strategySelector);
        this.championManager = new ChampionChallengerManager();

        // 初始化趋势检测器
        this.trendDetector = new MarketTrendDetector();

        // 初始化余额同步
        syncBalance();

        System.out.println("[ExecutionEngineV3] Initialized with " + strategies.size() + " strategies");
    }

    public ExecutionEngineV3(RiskManagerV2 riskManager, BinanceAdapterV2 adapter,
                              MetaLearner metaLearner, ChanExpert chanExpert) {
        this(riskManager, adapter, metaLearner, chanExpert, "ETHUSDT");
    }

    /**
     * 同步余额从交易所
     */
    private void syncBalance() {
        if (adapter != null) {
            adapter.syncBalanceFromExchange();
        }
    }

    /**
     * 获取可用余额
     */
    private double getAvailableBalance() {
        if (adapter != null) {
            return adapter.getAvailableBalance();
        }
        return 0;
    }

    /**
     * 主入口 - 处理信号
     */
    public void onSignal(CompositeSignal signal) {
        totalSignals.incrementAndGet();

        // Refresh balance before processing
        syncBalance();

        if (!signal.isValid()) {
            System.out.printf("[ExecutionEngineV3] Invalid signal: %s%n", signal);
            return;
        }

        // 风险检查
        if (!riskGate.allow(signal)) {
            riskRejects.incrementAndGet();
            return;
        }

        // V3: 使用StrategyRouter选择策略，而不是直接决定方向
        AlphaType selectedStrategy = selectStrategy(signal);

        // 获取策略方向
        TradeDirection direction = getStrategyDirection(selectedStrategy, signal);

        if (direction == TradeDirection.NEUTRAL) {
            System.out.printf("[ExecutionEngineV3] Strategy %s returned NEUTRAL, no trade%n", selectedStrategy);
            return;
        }

        // 模式决策
        ExecutionMode mode = stateMachine.decideMode(signal);

        // 首单强制开仓
        if (positionManager.isFlat() && signal.getConfidence() > 0.65) {
            mode = ExecutionMode.SMART_LIMIT;
            System.out.printf("[ExecutionEngineV3] First order forced: conf=%.2f > 0.65, mode=SMART_LIMIT%n",
                signal.getConfidence());
        }

        // 构建订单请求
        OrderRequest request = router.buildOrder(signal, mode, getAvailableBalance());
        request = OrderRequest.builder()
            .symbol(request.getSymbol())
            .side(direction)
            .orderType(request.getOrderType())
            .quantities(request.getQuantities())
            .price(request.getPrice())
            .mode(mode)
            .signal(signal)
            .timeInForce(request.getTimeInForce())
            .postOnly(request.isPostOnly())
            .build();

        // 提交订单
        orderManager.submit(request);
        totalOrders.incrementAndGet();

        System.out.printf("[ExecutionEngineV3] Signal processed: %s -> strategy=%s, dir=%s, mode=%s%n",
            signal, selectedStrategy, direction, mode);
    }

    /**
     * 选择策略 - 权重决定用哪个策略，不是决定方向
     * 策略方向由选中的策略自己根据市场状态决定
     */
    private AlphaType selectStrategy(CompositeSignal signal) {
        // 始终使用StrategyRouter根据权重和市场状态选择策略
        // 不依赖信号来源推断，因为Composite信号来源是"Composite:alpha-pool"没有语义信息
        MarketContext context = signalToContext(signal);
        Map<AlphaType, Double> weights = getDefaultWeights();

        AlphaType selected = strategyRouter.selectStrategy(weights, context);

        if (selected != lastActiveStrategy) {
            System.out.printf("[ExecutionEngineV3] Strategy changed: %s -> %s%n",
                lastActiveStrategy, selected);
            lastActiveStrategy = selected;
            strategyChanges.incrementAndGet();
        }

        return selected;
    }

    /**
     * 获取策略方向 - 由策略自己决定
     */
    private TradeDirection getStrategyDirection(AlphaType type, CompositeSignal signal) {
        TradingStrategy strategy = strategies.get(type);
        if (strategy == null) {
            // 默认使用均值回归
            strategy = strategies.get(AlphaType.MEAN_REVERSION);
        }

        MarketContext context = signalToContext(signal);
        double price = signal.getPrice();
        double atr = signal.getAtr() > 0 ? signal.getAtr() : price * 0.02;
        double upperBand = price + atr;
        double lowerBand = price - atr;

        TradeDirection dir = strategy.getDirection(context, price, upperBand, lowerBand);

        System.out.printf("[ExecutionEngineV3] Strategy %s: dir=%s, conf=%.2f%n",
            strategy.getName(), dir, strategy.getConfidence(context));

        return dir;
    }

    /**
     * 信号转MarketContext - 使用专业趋势检测
     */
    private MarketContext signalToContext(CompositeSignal signal) {
        double atrPercent = signal.getPrice() > 0 ? signal.getAtr() / signal.getPrice() : 0.0;

        // 使用专业趋势检测器替代简单的 confidence > 0.6 判断
        MarketTrendDetector.TrendDetectionResult trend = trendDetector.detect();

        // Debug: 每20个信号打印一次趋势检测结果
        if (totalSignals.get() % 20 == 0) {
            System.out.printf("[ExecutionEngineV3] TrendDetection: %s, history=%d%n",
                trend, trendDetector.getHistorySize());
        }

        // 获取检测到的市场状态
        MarketRegime regime = trend.getRegime();
        if (regime == null) {
            // 降级: 使用波动率判断
            regime = atrPercent > 0.015 ? MarketRegime.TREND_UP : MarketRegime.RANGE;
        }

        // 波动率状态
        VolatilityRegime volRegime = atrPercent > 0.02
            ? VolatilityRegime.HIGH
            : atrPercent > 0.01
                ? VolatilityRegime.MEDIUM
                : VolatilityRegime.LOW;

        // 趋势强度映射
        TrendStrength strength;
        switch (trend.getIntensity()) {
            case STRONG: strength = TrendStrength.STRONG; break;
            case MODERATE: strength = TrendStrength.MODERATE; break;
            case WEAK: strength = TrendStrength.WEAK; break;
            default: strength = TrendStrength.NONE;
        }

        return MarketContext.builder()
            .currentPrice(signal.getPrice())
            .atr(signal.getAtr())
            .atrPercent(atrPercent)
            .regime(regime)
            .volatilityRegime(volRegime)
            .trendStrength(strength)
            .build();
    }

    /**
     * 获取默认权重（临时用，后续接入MetaLearner）
     */
    private Map<AlphaType, Double> getDefaultWeights() {
        Map<AlphaType, Double> weights = new ConcurrentHashMap<>();
        weights.put(AlphaType.MEAN_REVERSION, 0.333);
        weights.put(AlphaType.TREND_FOLLOWING, 0.333);
        weights.put(AlphaType.VOLATILITY, 0.333);
        return weights;
    }

    /**
     * 处理AlphaPool信号
     */
    public void onAlphaSignal(CompositeAlphaSignal signal) {
        CompositeSignal cs = CompositeSignal.fromAlphaSignal(signal);
        onSignal(cs);
    }

    /**
     * 通知市场数据给Champion-Challenger系统和趋势检测器
     */
    public void feedMarketData(MarketData data, ChanMarketState state, ChanPricePoint point) {
        if (championManager != null) {
            championManager.feedMarketData("dna-strategy", data, state, point);
        }

        // 更新趋势检测器
        if (data != null && data.getLastPrice() > 0) {
            double atr = data.getVolatility() > 0 ? data.getVolatility() : data.getLastPrice() * 0.02;
            double atrPercent = atr / data.getLastPrice();
            double bidSize = data.getBidSize();
            double askSize = data.getAskSize();

            trendDetector.update(data.getLastPrice(), atr, atrPercent, bidSize, askSize);
        }
    }

    /**
     * 更新OFI数据给趋势检测器
     */
    public void feedOFI(double ofi, double tradeFlow) {
        trendDetector.updateOFI(ofi, tradeFlow);
    }

    /**
     * 更新仓位
     */
    public void onExecutionReport(ExecutionReport report) {
        if (report == null) return;
        positionManager.onFill(report);
        orderManager.onExecutionReport(report);
    }

    public void incrementFlatCounter() {
        positionManager.incrementFlatCounter();
    }

    public double getPosition() {
        return positionManager.getPosition();
    }

    public PositionManager.PositionState getPositionState() {
        return positionManager.getState();
    }

    public boolean isFlat() {
        return positionManager.isFlat();
    }

    public String getStats() {
        return String.format("ExecutionEngineV3{signals=%d, orders=%d, rejects=%d, pos=%.4f, state=%s, strategyChanges=%d}",
            totalSignals.get(), totalOrders.get(), riskRejects.get(),
            positionManager.getPosition(), positionManager.getState(), strategyChanges.get());
    }

    public void shutdown() {
        orderManager.shutdown();
        if (pluginEngine != null) pluginEngine.shutdown();
        if (championManager != null) championManager.stop();
        System.out.println("[ExecutionEngineV3] Shutdown complete");
    }
}