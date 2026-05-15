package com.trading.test;

import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.risk.RiskManagerV2;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderIntent;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.config.ConfigUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 测试脚本：强制触发下单以调试-2010错误
 */
public class ForceOrderTest {
    private static final Logger log = LoggerFactory.getLogger(ForceOrderTest.class);

    public static void main(String[] args) {
        log.info("[ForceOrderTest] Starting...");

        // 获取API配置
        String apiKey = ConfigUtil.get("api.key");
        String apiSecret = ConfigUtil.get("api.secret");
        boolean paperTrading = ConfigUtil.getBoolean("PAPER_TRADING");

        log.info("[ForceOrderTest] paperTrading={}", paperTrading);

        // 创建RiskManagerV2（实现RiskManager接口）
        RiskManagerV2 rm = new RiskManagerV2(10000.0, 0.2);

        // 创建ExecutionEngine（live模式）
        ExecutionEngine engine = new ExecutionEngine(rm, paperTrading, apiKey, apiSecret);

        // 同步余额
        double balance = engine.getExchangeAdapter().syncBalanceFromExchange();
        log.info("[ForceOrderTest] Balance: {} USDT", balance);

        // 设置杠杆
        engine.getExchangeAdapter().setLeverage(10);
        log.info("[ForceOrderTest] Leverage set to 10x");

        // 启动引擎
        engine.start();

        // 等待启动
        try { Thread.sleep(2000); } catch (Exception e) {}

        // 创建一个测试订单 - OPEN_SHORT (做空)
        String orderId = "test_open_short_" + System.currentTimeMillis();
        Order testOrder = new Order(
            orderId,
            "BTCUSDT",
            TradeDirection.SHORT,
            OrderType.MARKET,
            0.001,  // 0.001 BTC
            82000.0, // 参考价格
            "test",
            1.0
        );

        // 设置Intent
        testOrder.setIntent(OrderIntent.OPEN_SHORT);

        log.info("[ForceOrderTest] Submitting test order: id={}, side={}, qty={}, intent={}",
                orderId, TradeDirection.SHORT, 0.001, OrderIntent.OPEN_SHORT);

        // 提交订单
        boolean accepted = engine.submitOrder(testOrder);

        log.info("[ForceOrderTest] Order accepted: {}", accepted);

        // 等待处理
        try { Thread.sleep(5000); } catch (Exception e) {}

        // 停止引擎
        engine.stop();

        log.info("[ForceOrderTest] Done");
        System.exit(0);
    }
}