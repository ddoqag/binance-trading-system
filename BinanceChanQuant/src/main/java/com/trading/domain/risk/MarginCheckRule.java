package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Margin Check Rule - ensures order value doesn't exceed available margin.
 */
public class MarginCheckRule implements RiskRule {

    private final String name;
    private final AtomicReference<Double> availableMargin;
    private final double maxOrderValue;

    public MarginCheckRule(double maxOrderValue) {
        this("MarginCheck", maxOrderValue, new AtomicReference<>(0.0));
    }

    public MarginCheckRule(String name, double maxOrderValue, AtomicReference<Double> availableMargin) {
        this.name = name;
        this.maxOrderValue = maxOrderValue;
        this.availableMargin = availableMargin;
    }

    @Override
    public String getName() {
        return name;
    }

    @Override
    public CheckResult check(Order order) {
        double orderValue = order.getQuantity() * order.getPrice();

        if (orderValue > maxOrderValue) {
            return CheckResult.reject(
                "Order value " + String.format("%.2f", orderValue) + " exceeds max " + maxOrderValue,
                "ORDER_VALUE_EXCEEDED"
            );
        }

        double margin = availableMargin.get();
        if (margin > 0 && orderValue > margin) {
            return CheckResult.reject(
                "Order value " + String.format("%.2f", orderValue) + " exceeds margin " + String.format("%.2f", margin),
                "MARGIN_EXCEEDED"
            );
        }

        return CheckResult.pass();
    }

    @Override
    public int getPriority() {
        return 80;  // High priority
    }

    public void updateMargin(double margin) {
        availableMargin.set(margin);
    }
}