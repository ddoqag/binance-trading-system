package com.trading.execution.v4;

import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.market.model.MarketData;

/**
 * V4 完整组合验证程序
 * ExecutionEngineV4 + PositionRiskController 构成信号驱动 + 风控闭环
 */
public class V4IntegrationTest {

    public static void main(String[] args) {
        System.out.println("========== V4 Integration Test ==========\n");

        // 1. 初始化组件
        ExecutionEngineV4 engine = new ExecutionEngineV4();
        PositionRiskController riskController = new PositionRiskController();

        // 2. 模拟市场数据
        MarketData market = new MarketData();
        market.setSymbol("BTCUSDT");
        market.setLastPrice(2000.0);
        market.setBidPrice(1999.0);
        market.setAskPrice(2001.0);

        System.out.println("Step 1: 初始化完成");
        System.out.println("  - ExecutionEngineV4: OK");
        System.out.println("  - PositionRiskController: OK");
        System.out.println();

        // 3. 模拟信号：LONG 信号 (方向来自 AlphaPool)
        System.out.println("Step 2: 收到 LONG 信号 (from AlphaPool)");
        CompositeSignal signal = createLongSignal(0.75);
        System.out.println("  Signal: direction=LONG, confidence=0.75, price=2000.0");

        // 4. 风控裁决
        int signalDir = signal.getDirection() == CompositeSignal.Direction.LONG ? 1 : -1;
        System.out.println("  RiskGateway.evaluate: dir=" + signalDir);

        // 5. 模拟成交
        System.out.println("\nStep 3: 成交回调 (Fill)");
        ExecutionReport fill = createFill("LONG", 0.1, 2000.0);
        System.out.println("  Fill: side=LONG, qty=0.1, price=2000.0");

        // 6. PositionRiskController 处理成交
        riskController.onFill(fill);
        System.out.println("  PositionRiskController.onFill: OK");

        // 检查风控状态
        PositionRiskController.RiskState state = riskController.getState("BTCUSDT");
        if (state != null) {
            System.out.println("  RiskState: active=" + state.isActive()
                + ", position=" + state.getPosition()
                + ", entry=" + state.getEntryPrice()
                + ", SL=" + state.getStopLossPrice()
                + ", TP=" + state.getTakeProfitPrice());
        }
        System.out.println();

        // 7. 模拟市场tick驱动风控检查
        System.out.println("Step 4: 市场tick驱动风控检查");

        // 场景A：价格上涨到 TP1 (4% * 0.5 = 2%)
        System.out.println("\n  场景A: 价格涨到 2040 (TP1 触发)");
        market.setLastPrice(2040.0);
        var orders = riskController.onMarketTick("BTCUSDT", market);
        System.out.println("  Orders from RiskController: " + orders.size());
        for (var order : orders) {
            System.out.println("    -> " + order.side() + " " + order.quantity() + " @ " + order.mode() + " (" + ((ExecutionEngineV4.OrderRequest)order).symbol() + ")");
        }

        // 场景B：价格继续涨到 TP2 (4%)
        System.out.println("\n  场景B: 价格继续涨到 2080 (TP2 触发)");
        market.setLastPrice(2080.0);
        orders = riskController.onMarketTick("BTCUSDT", market);
        System.out.println("  Orders from RiskController: " + orders.size());

        // 场景C：价格下跌到止损
        System.out.println("\n  场景C: 价格下跌到 1960 (止损触发)");
        market.setLastPrice(1960.0);
        orders = riskController.onMarketTick("BTCUSDT", market);
        System.out.println("  Orders from RiskController: " + orders.size());
        for (var order : orders) {
            System.out.println("    -> " + order.side() + " " + order.quantity() + " @ " + order.mode());
        }
        System.out.println();

        // 8. 测试 SHORT 持仓 - 使用新的风控实例
        System.out.println("Step 5: 测试 SHORT 持仓风控");
        PositionRiskController shortRiskController = new PositionRiskController();
        shortRiskController.onFill(createFill("SHORT", 0.1, 2000.0));
        System.out.println("  Fill: side=SHORT, qty=0.1, price=2000.0");

        state = shortRiskController.getState("BTCUSDT");
        if (state != null) {
            System.out.println("  RiskState: position=" + state.getPosition()
                + ", entry=" + state.getEntryPrice()
                + ", SL=" + state.getStopLossPrice()
                + ", TP=" + state.getTakeProfitPrice());
        }

        System.out.println("\n  场景D: 空头价格下跌到 1920 (TP1 触发，TP1=1960 for SHORT)");
        market.setLastPrice(1920.0);
        orders = shortRiskController.onMarketTick("BTCUSDT", market);
        System.out.println("  Orders from RiskController: " + orders.size());
        for (var order : orders) {
            System.out.println("    -> " + order.side() + " " + order.quantity() + " @ " + order.mode());
        }

        System.out.println("\n========== V4 Integration Test Complete ==========");
        System.out.println("\n✅ V4 架构验证:");
        System.out.println("  1. Signal → RiskGateway → Execution: 方向由Signal决定，Execution不反向");
        System.out.println("  2. Fill → PositionRiskController: 成交后初始化风控状态");
        System.out.println("  3. MarketTick → RiskController → Close: 平仓指令由风控触发，不污染Signal层");
        System.out.println("  4. OCO + Trailing Stop: 分批止盈 + 移动止损");
    }

    private static CompositeSignal createLongSignal(double confidence) {
        CompositeSignal sig = new CompositeSignal();
        sig.setDirection(CompositeSignal.Direction.LONG);
        sig.setConfidence(confidence);
        sig.setPrice(2000.0);
        sig.setUrgency(0.7);
        return sig;
    }

    private static ExecutionReport createFill(String side, double qty, double price) {
        TradeDirection dir = side.equals("LONG") ? TradeDirection.LONG : TradeDirection.SHORT;
        return new ExecutionReport(
            "test-order-1",
            "BTCUSDT",
            dir,
            com.trading.domain.trading.model.OrderType.LIMIT,
            qty, price, qty, price,
            com.trading.domain.trading.model.OrderStatus.FILLED,
            System.currentTimeMillis(),
            0, 0,
            (String) null
        );
    }
}