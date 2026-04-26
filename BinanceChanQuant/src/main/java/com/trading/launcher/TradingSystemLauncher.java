package com.trading.launcher;

import com.trading.config.ConfigUtil;

/**
 * Trading System Launcher
 * Main entry point for the refactored trading system
 */
public class TradingSystemLauncher {

    public static void main(String[] args) {
        System.out.println("============================================================");
        System.out.println("Trading System V4.0 - Clean Architecture");
        System.out.println("============================================================");

        // Load configuration
        String symbol = ConfigUtil.get("symbol");
        String apiKey = ConfigUtil.get("api.key");
        boolean testnet = ConfigUtil.isTestNet();

        System.out.println("Symbol: " + symbol);
        System.out.println("API Key: " + (apiKey.isEmpty() ? "(empty)" : "***"));
        System.out.println("Testnet: " + testnet);
        System.out.println("============================================================");

        // Note: Full implementation will be completed in Phase 2-3
        System.out.println("System initialized. Full launch will be available after Phase 3.");
    }
}
