package com.trading.actors;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.*;
import com.trading.messaging.messages.*;

import java.util.concurrent.atomic.AtomicReference;

/**
 * Risk Actor - handles all risk-related messages.
 * Receives risk check commands and publishes risk events.
 */
public class RiskActor extends Actor {

    // Risk limits
    private static final double MAX_POSITION_SIZE = 10.0;
    private static final double MAX_DAILY_LOSS = 300.0;
    private static final int MAX_DAILY_TRADES = 100;

    // Current state (using AtomicReference for thread-safety without locks)
    private final AtomicReference<RiskState> state = new AtomicReference<>(new RiskState());

    public RiskActor() {
        super("RiskActor");
    }

    @Override
    public void receive(Command command) {
        if (command instanceof CheckRiskCommand) {
            handleRiskCheck((CheckRiskCommand) command);
        } else if (command instanceof UpdateRiskStateCommand) {
            handleUpdateState((UpdateRiskStateCommand) command);
        }
    }

    @Override
    public void receive(DomainEvent event) {
        if (event instanceof OrderFilledEvent) {
            handleOrderFilled((OrderFilledEvent) event);
        } else if (event instanceof OrderCancelledEvent) {
            handleOrderCancelled((OrderCancelledEvent) event);
        }
    }

    private void handleRiskCheck(CheckRiskCommand cmd) {
        RiskState current = state.get();

        // Check 1: Max position size
        double newPosition = calculateNewPosition(cmd.side(), cmd.quantity(), current.position());
        if (Math.abs(newPosition) > MAX_POSITION_SIZE) {
            publish(new RiskLimitExceededEvent(
                cmd.orderId(), cmd.symbol(), cmd.quantity(), cmd.price(),
                "Max position size exceeded: " + Math.abs(newPosition) + " > " + MAX_POSITION_SIZE
            ));
            return;
        }

        // Check 2: Daily loss limit
        if (current.dailyPnl() < -MAX_DAILY_LOSS) {
            publish(new RiskLimitExceededEvent(
                cmd.orderId(), cmd.symbol(), cmd.quantity(), cmd.price(),
                "Daily loss limit exceeded: " + current.dailyPnl() + " < " + (-MAX_DAILY_LOSS)
            ));
            return;
        }

        // Check 3: Daily trade count
        if (current.dailyTrades() >= MAX_DAILY_TRADES) {
            publish(new RiskLimitExceededEvent(
                cmd.orderId(), cmd.symbol(), cmd.quantity(), cmd.price(),
                "Daily trade limit exceeded: " + current.dailyTrades() + " >= " + MAX_DAILY_TRADES
            ));
            return;
        }

        // Check 4: Balance check
        double requiredMargin = cmd.quantity() * cmd.price() / 20; // 2x leverage = 50% margin
        if (requiredMargin > current.availableBalance() * 0.8) {
            publish(new RiskLimitExceededEvent(
                cmd.orderId(), cmd.symbol(), cmd.quantity(), cmd.price(),
                "Insufficient balance for margin: " + requiredMargin + " > " + (current.availableBalance() * 0.8)
            ));
            return;
        }

        // All checks passed
        publish(new RiskCheckPassedEvent(cmd.orderId(), cmd.symbol(), cmd.quantity(), cmd.price()));
    }

    private void handleUpdateState(UpdateRiskStateCommand cmd) {
        state.updateAndGet(current -> new RiskState(
            cmd.equity(),
            Math.max(cmd.equity(), current.peakEquity()),
            cmd.dailyPnl(),
            cmd.dailyTrades(),
            cmd.dailyRejects(),
            current.consecutiveLosses(),
            current.circuitBreakerTriggered()
        ));
    }

    private void handleOrderFilled(OrderFilledEvent filled) {
        state.updateAndGet(current -> {
            int newTrades = current.dailyTrades() + 1;
            double newPnl = current.dailyPnl() + filled.realizedPnl();
            int newLosses = filled.realizedPnl() < 0 ? current.consecutiveLosses() + 1 : 0;

            return new RiskState(
                current.equity() + filled.realizedPnl(),
                Math.max(current.equity() + filled.realizedPnl(), current.peakEquity()),
                newPnl,
                newTrades,
                current.dailyRejects(),
                newLosses,
                newLosses >= 3 || current.circuitBreakerTriggered()
            );
        });
    }

    private void handleOrderCancelled(OrderCancelledEvent cancelled) {
        // No state change needed for cancellations
    }

    private double calculateNewPosition(TradeDirection side, double quantity, double currentPosition) {
        switch (side) {
            case LONG:
                return currentPosition + quantity;
            case SHORT:
                return currentPosition - quantity;
            case CLOSE:
                return currentPosition - quantity;
            default:
                return currentPosition;
        }
    }

    // Immutable Risk State
    public static class RiskState {
        private final double equity;
        private final double peakEquity;
        private final double dailyPnl;
        private final int dailyTrades;
        private final int dailyRejects;
        private final int consecutiveLosses;
        private final boolean circuitBreakerTriggered;

        public RiskState() {
            this.equity = 0;
            this.peakEquity = 0;
            this.dailyPnl = 0;
            this.dailyTrades = 0;
            this.dailyRejects = 0;
            this.consecutiveLosses = 0;
            this.circuitBreakerTriggered = false;
        }

        public RiskState(double equity, double peakEquity, double dailyPnl,
                        int dailyTrades, int dailyRejects, int consecutiveLosses,
                        boolean circuitBreakerTriggered) {
            this.equity = equity;
            this.peakEquity = peakEquity;
            this.dailyPnl = dailyPnl;
            this.dailyTrades = dailyTrades;
            this.dailyRejects = dailyRejects;
            this.consecutiveLosses = consecutiveLosses;
            this.circuitBreakerTriggered = circuitBreakerTriggered;
        }

        public double equity() { return equity; }
        public double peakEquity() { return peakEquity; }
        public double dailyPnl() { return dailyPnl; }
        public int dailyTrades() { return dailyTrades; }
        public int dailyRejects() { return dailyRejects; }
        public int consecutiveLosses() { return consecutiveLosses; }
        public boolean circuitBreakerTriggered() { return circuitBreakerTriggered; }
        public double availableBalance() { return equity; }
        public double position() { return 0; }
    }
}
