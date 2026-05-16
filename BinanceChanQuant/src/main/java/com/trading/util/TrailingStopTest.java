package com.trading.util;

import com.trading.adapter.execution.BinanceAlgoClient;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import java.net.Proxy;
import java.net.InetSocketAddress;

/**
 * Test trailing stop placement
 */
public class TrailingStopTest {

    public static void main(String[] args) throws Exception {
        System.out.println("=== Trailing Stop Test ===");

        String apiKey = "aViqrCfrE2iFzbD5exSDIn396AlyrjmjMPnaNHozBNJ501l0iGQMRIzp1rdMn3ju";
        String apiSecret = "T9mKg7CL5lgtc3WDIpyZPM2O5KQcjk78EAGMq1E4ObJGxF2ZXddlwAiPyGreC531";
        String baseUrl = "https://fapi.binance.com";

        Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress("127.0.0.1", 7897));

        System.out.println("[1] Creating BinanceAlgoClient...");
        BinanceAlgoClient algoClient = new BinanceAlgoClient(apiKey, apiSecret, baseUrl, proxy);

        System.out.println("[2] Placing test trailing stop...");
        System.out.println("  Symbol: BTCUSDT");
        System.out.println("  Quantity: 0.001");
        System.out.println("  ActivatePrice: 80000 (trailing stop for SHORT position)");
        System.out.println("  CallbackRate: 0.8%");

        String orderId = "test-trailing-" + System.currentTimeMillis();
        // For SHORT position: use SELL with positionSide=SHORT
        // This is a sell trailing stop - activates when price rises to 80000
        // Then trails down by 0.8%
        Order order = new Order(orderId, "BTCUSDT", TradeDirection.SHORT,
            OrderType.STOP_MARKET, 0.001, 80000.0, "trailing", 1.0);
        order.setStopPrice(80000.0);
        // Don't set closePosition for trailing stop - use reduceOnly instead

        var report = algoClient.sendTrailingStopOrder(order, 0.8);

        System.out.println("\n[3] Result:");
        System.out.println("  Status: " + (report != null ? report.getStatus() : "NULL"));
        if (report != null) {
            System.out.println("  Exchange ID: " + report.getExchangeOrderId());
            System.out.println("  Reject Reason: " + report.getRejectReason());
        }
    }
}