package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Daily Loss Limit Rule - enforces maximum daily loss.
 */
public class DailyLossLimitRule implements RiskRule {

    private final String name;
    private final double maxDailyLoss;
    private final AtomicReference<Double> dailyPnl;

    public DailyLossLimitRule(double maxDailyLoss) {
        this("DailyLossLimit", maxDailyLoss, new AtomicReference<>(0.0));
    }

    public DailyLossLimitRule(String name, double maxDailyLoss, AtomicReference<Double> dailyPnl) {
        this.name = name;
        this.maxDailyLoss = maxDailyLoss;
        this.dailyPnl = dailyPnl;
    }

    @Override
    public String getName() {
        return name;
    }

    @Override
    public CheckResult check(Order order) {
        double pnl = dailyPnl.get();

        if (pnl < -maxDailyLoss) {
            return CheckResult.reject(
                "Daily loss " + String.format("%.2f", pnl) + " exceeds limit " + (-maxDailyLoss),
                "DAILY_LOSS_EXCEEDED"
            );
        }

        return CheckResult.pass();
    }

    @Override
    public int getPriority() {
        return 50;
    }

    public void updateDailyPnl(double pnl) {
        dailyPnl.set(pnl);
    }
}