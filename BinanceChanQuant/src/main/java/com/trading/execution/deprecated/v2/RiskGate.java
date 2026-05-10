package com.trading.execution.v2;

import com.trading.adapter.risk.RiskManagerV2;
import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskCheckResult;

/**
 * Risk Gate - Simplified risk checks delegating to RiskManagerV2
 */
public class RiskGate {

    private final RiskManagerV2 riskManager;

    public RiskGate(RiskManagerV2 riskManager) {
        this.riskManager = riskManager;
    }

    /**
     * Check if signal passes risk gates
     */
    public boolean allow(CompositeSignal signal) {
        // 1. Confidence threshold
        if (signal.getConfidence() < 0.2) {
            System.out.printf("[RiskGate] Rejected: confidence %.2f < 0.2%n", signal.getConfidence());
            return false;
        }

        // 2. RiskManager check
        Order order = signalToOrder(signal);
        RiskCheckResult result = riskManager.preTradeCheck(order, signal.getPrice());

        if (!result.isAllowed()) {
            System.out.printf("[RiskGate] Rejected by riskManager: %s%n", result.getMessage());
            return false;
        }

        // 3. Direction conflict check
        double netPosition = riskManager.getNetPosition();
        if (netPosition > 0.0001 && signal.getDirection() == CompositeSignal.Direction.SHORT) {
            System.out.println("[RiskGate] Rejected: LONG position, SHORT signal conflict");
            return false;
        }
        if (netPosition < -0.0001 && signal.getDirection() == CompositeSignal.Direction.LONG) {
            System.out.println("[RiskGate] Rejected: SHORT position, LONG signal conflict");
            return false;
        }

        return true;
    }

    private Order signalToOrder(CompositeSignal signal) {
        TradeDirection dir = CompositeSignal.toTradeDirection(signal.getDirection());
        return new Order(
            "risk-check-" + System.nanoTime(),
            "BTCUSDT",
            dir,
            OrderType.LIMIT,
            0.01,  // placeholder quantity for risk check
            signal.getPrice(),
            "RISK_GATE",
            signal.getUrgency()
        );
    }
}
