package com.trading.actors;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.*;
import com.trading.messaging.messages.*;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Position Actor - manages positions and calculates PnL.
 * Receives position commands and publishes position events.
 */
public class PositionActor extends Actor {

    // Thread-safe position state per symbol
    private final Map<String, PositionState> positions = new ConcurrentHashMap<>();

    public PositionActor() {
        super("PositionActor");
    }

    @Override
    public void receive(Command command) {
        if (command instanceof OpenPositionCommand) {
            handleOpen((OpenPositionCommand) command);
        } else if (command instanceof ClosePositionCommand) {
            handleClose((ClosePositionCommand) command);
        } else if (command instanceof UpdatePositionCommand) {
            handleUpdate((UpdatePositionCommand) command);
        }
    }

    @Override
    public void receive(DomainEvent event) {
        if (event instanceof OrderFilledEvent) {
            handleOrderFilled((OrderFilledEvent) event);
        }
    }

    private void handleOpen(OpenPositionCommand cmd) {
        PositionState current = positions.get(cmd.symbol());

        if (current == null) {
            // New position
            PositionState newState = new PositionState(
                cmd.symbol(),
                cmd.side(),
                cmd.quantity(),
                cmd.entryPrice(),
                cmd.quantity() * cmd.entryPrice(),  // cost
                0.0  // realized PnL
            );
            positions.put(cmd.symbol(), newState);
            publish(new PositionOpenedEvent(
                cmd.symbol() + "-" + System.currentTimeMillis(),
                cmd.symbol(),
                cmd.side(),
                cmd.quantity(),
                cmd.entryPrice()
            ));
        } else {
            // Add to existing position
            PositionState updated = current.addFill(cmd.side(), cmd.quantity(), cmd.entryPrice());
            positions.put(cmd.symbol(), updated);
            publish(new PositionModifiedEvent(
                cmd.symbol(),
                cmd.symbol(),
                updated.side(),
                updated.quantity(),
                updated.avgEntryPrice(),
                updated.unrealizedPnl()
            ));
        }
    }

    private void handleClose(ClosePositionCommand cmd) {
        PositionState current = positions.get(cmd.symbol());
        if (current == null) return;

        PositionState updated = current.reduce(cmd.quantity(), cmd.exitPrice());
        if (updated.quantity() <= 0.0001) {
            // Position closed
            positions.remove(cmd.symbol());
            publish(new PositionClosedEvent(
                cmd.symbol(),
                cmd.symbol(),
                current.side(),
                current.quantity(),
                current.avgEntryPrice(),
                updated.realizedPnl()
            ));
        } else {
            positions.put(cmd.symbol(), updated);
            publish(new PositionModifiedEvent(
                cmd.symbol(),
                cmd.symbol(),
                updated.side(),
                updated.quantity(),
                updated.avgEntryPrice(),
                updated.unrealizedPnl()
            ));
        }
    }

    private void handleUpdate(UpdatePositionCommand cmd) {
        PositionState current = positions.get(cmd.symbol());
        if (current == null) return;

        double unrealizedPnl = current.calculateUnrealizedPnl(cmd.currentPrice());
        PositionState updated = current.withUnrealizedPnl(unrealizedPnl);
        positions.put(cmd.symbol(), updated);
    }

    private void handleOrderFilled(OrderFilledEvent filled) {
        PositionState current = positions.get(filled.symbol());

        if (current == null) {
            // New position from fill
            if (filled.filledQuantity() > 0) {
                PositionState newState = new PositionState(
                    filled.symbol(),
                    filled.side(),
                    filled.filledQuantity(),
                    filled.avgFillPrice(),
                    filled.filledQuantity() * filled.avgFillPrice(),
                    0.0
                );
                positions.put(filled.symbol(), newState);
                publish(new PositionOpenedEvent(
                    filled.symbol() + "-" + System.currentTimeMillis(),
                    filled.symbol(),
                    filled.side(),
                    filled.filledQuantity(),
                    filled.avgFillPrice()
                ));
            }
        } else {
            // Update existing position
            PositionState updated = current.addFill(filled.side(), filled.filledQuantity(), filled.avgFillPrice());
            positions.put(filled.symbol(), updated);
            publish(new PositionModifiedEvent(
                filled.symbol(),
                filled.symbol(),
                updated.side(),
                updated.quantity(),
                updated.avgEntryPrice(),
                updated.unrealizedPnl()
            ));
        }
    }

    // Get current position
    public double getPosition(String symbol) {
        PositionState state = positions.get(symbol);
        return state != null ? state.quantity() : 0.0;
    }

    public double getUnrealizedPnl(String symbol) {
        PositionState state = positions.get(symbol);
        return state != null ? state.unrealizedPnl() : 0.0;
    }

    // Immutable Position State
    public static class PositionState {
        private final String symbol;
        private final TradeDirection side;
        private final double quantity;
        private final double avgEntryPrice;
        private final double cost;
        private final double realizedPnl;
        private final double unrealizedPnl;

        public PositionState(String symbol, TradeDirection side, double quantity,
                          double avgEntryPrice, double cost, double realizedPnl) {
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.avgEntryPrice = avgEntryPrice;
            this.cost = cost;
            this.realizedPnl = realizedPnl;
            this.unrealizedPnl = 0.0;
        }

        private PositionState(String symbol, TradeDirection side, double quantity,
                           double avgEntryPrice, double cost, double realizedPnl, double unrealizedPnl) {
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.avgEntryPrice = avgEntryPrice;
            this.cost = cost;
            this.realizedPnl = realizedPnl;
            this.unrealizedPnl = unrealizedPnl;
        }

        public String symbol() { return symbol; }
        public TradeDirection side() { return side; }
        public double quantity() { return quantity; }
        public double avgEntryPrice() { return avgEntryPrice; }
        public double cost() { return cost; }
        public double realizedPnl() { return realizedPnl; }
        public double unrealizedPnl() { return unrealizedPnl; }

        public PositionState addFill(TradeDirection fillSide, double fillQty, double fillPrice) {
            double newCost = cost + fillQty * fillPrice;
            double newQty = quantity + fillQty;
            double newAvgPrice = newQty > 0 ? newCost / newQty : 0;
            return new PositionState(symbol, side, newQty, newAvgPrice, newCost, realizedPnl, unrealizedPnl);
        }

        public PositionState reduce(double reduceQty, double exitPrice) {
            double pnl = 0;
            if (side == TradeDirection.LONG) {
                pnl = (exitPrice - avgEntryPrice) * reduceQty;
            } else if (side == TradeDirection.SHORT) {
                pnl = (avgEntryPrice - exitPrice) * reduceQty;
            }
            double newQty = quantity - reduceQty;
            double newRealizedPnl = realizedPnl + pnl;
            return new PositionState(symbol, side, newQty, avgEntryPrice, cost, newRealizedPnl, unrealizedPnl);
        }

        public PositionState withUnrealizedPnl(double pnl) {
            return new PositionState(symbol, side, quantity, avgEntryPrice, cost, realizedPnl, pnl);
        }

        public double calculateUnrealizedPnl(double currentPrice) {
            if (Math.abs(quantity) < 0.0001) return 0.0;
            if (side == TradeDirection.LONG) {
                return (currentPrice - avgEntryPrice) * quantity;
            } else if (side == TradeDirection.SHORT) {
                return (avgEntryPrice - currentPrice) * quantity;
            }
            return 0.0;
        }
    }
}
