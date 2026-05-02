package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Max Position Rule - enforces maximum position size per symbol.
 */
public class MaxPositionRule implements RiskRule {

    private final String name;
    private final double maxPosition;
    private final AtomicReference<Double> currentPosition;

    public MaxPositionRule(double maxPosition) {
        this("MaxPosition", maxPosition, new AtomicReference<>(0.0));
    }

    public MaxPositionRule(String name, double maxPosition, AtomicReference<Double> currentPosition) {
        this.name = name;
        this.maxPosition = maxPosition;
        this.currentPosition = currentPosition;
    }

    @Override
    public String getName() {
        return name;
    }

    @Override
    public CheckResult check(Order order) {
        double current = currentPosition.get();
        double requested = order.getQuantity();

        double newPosition;
        if (order.getSide() == TradeDirection.LONG) {
            newPosition = current + requested;
        } else if (order.getSide() == TradeDirection.SHORT) {
            newPosition = current - requested;
        } else {
            // CLOSE - position going to zero
            newPosition = 0;
        }

        if (Math.abs(newPosition) > maxPosition) {
            return CheckResult.reject(
                "Position " + String.format("%.4f", newPosition) + " exceeds max " + maxPosition,
                "MAX_POSITION_EXCEEDED"
            );
        }

        return CheckResult.pass();
    }

    @Override
    public int getPriority() {
        return 100;  // High priority - position check early
    }

    public void updatePosition(double position) {
        currentPosition.set(position);
    }
}