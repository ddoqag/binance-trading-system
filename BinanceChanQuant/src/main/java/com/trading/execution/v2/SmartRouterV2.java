package com.trading.execution.v2;

import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.execution.ExecutionMode;

import java.util.ArrayList;
import java.util.List;

/**
 * Smart Router V2 - Dynamic order type/price/size based on mode and signal
 */
public class SmartRouterV2 {

    private static final double DEFAULT_ATR_PERCENT = 0.0002;
    private final String symbol;

    public SmartRouterV2(String symbol) {
        this.symbol = symbol != null ? symbol : "ETHUSDT";
    }

    public SmartRouterV2() {
        this("ETHUSDT");
    }

    /**
     * Build OrderRequest from signal + mode
     * @param signal the trading signal
     * @param mode the execution mode
     * @param availableBalance available USDT balance for dynamic sizing (0 = use default)
     */
    public OrderRequest buildOrder(CompositeSignal signal, ExecutionMode mode, double availableBalance) {
        // 1. Determine order type
        OrderType orderType = getOrderType(mode);

        // 2. Calculate price with slippage
        double slippage = calculateSlippage(signal, mode);
        double price = adjustPriceForSlippage(signal.getPrice(), slippage, signal.getDirection());

        // 3. Calculate quantity - use available balance if provided
        double baseQty = calculateQuantity(signal, availableBalance, price);
        List<Double> quantities = splitIfNeeded(baseQty, mode);

        // 4. Time in force
        int timeInForce = getTimeInForce(mode);

        // 5. Post-only for passive
        boolean postOnly = mode == ExecutionMode.PASSIVE;

        return OrderRequest.builder()
            .symbol(symbol)
            .side(CompositeSignal.toTradeDirection(signal.getDirection()))
            .orderType(orderType)
            .quantities(quantities)
            .price(price)
            .mode(mode)
            .signal(signal)
            .timeInForce(timeInForce)
            .postOnly(postOnly)
            .build();
    }

    /**
     * Build OrderRequest with default quantity (backward compatible)
     */
    public OrderRequest buildOrder(CompositeSignal signal, ExecutionMode mode) {
        return buildOrder(signal, mode, 0);
    }

    private OrderType getOrderType(ExecutionMode mode) {
        switch (mode) {
            case PASSIVE: return OrderType.LIMIT;
            case SMART_LIMIT: return OrderType.LIMIT;
            case AGGRESSIVE: return OrderType.IOC;
            case KILL_SWITCH: return OrderType.MARKET;
            default: return OrderType.LIMIT;
        }
    }

    private int getTimeInForce(ExecutionMode mode) {
        switch (mode) {
            case PASSIVE: return 3600;
            case SMART_LIMIT: return 300;
            case AGGRESSIVE: return 60;
            case KILL_SWITCH: return 10;
            default: return 300;
        }
    }

    private double calculateSlippage(CompositeSignal signal, ExecutionMode mode) {
        double baseSlippage;
        switch (mode) {
            case PASSIVE: baseSlippage = 0.0; break;
            case SMART_LIMIT: baseSlippage = 0.0; break;  // No slippage for limit orders - use market price directly
            case AGGRESSIVE: baseSlippage = 0.001; break;
            case KILL_SWITCH: baseSlippage = 0.01; break;
            default: baseSlippage = 0.0;
        }

        // Increase slippage based on ATR/volatility
        double atrPercent = signal.getAtr() / signal.getPrice();
        if (atrPercent <= 0) atrPercent = DEFAULT_ATR_PERCENT;
        double volatilityMultiplier = 1.0 + atrPercent * 10;

        return baseSlippage * volatilityMultiplier;
    }

    private double adjustPriceForSlippage(double price, double slippage, CompositeSignal.Direction dir) {
        if (slippage <= 0) return normalizePrice(price);

        double adjusted;
        switch (dir) {
            case LONG: adjusted = price * (1 + slippage); break;
            case SHORT: adjusted = price * (1 - slippage); break;
            default: adjusted = price;
        }

        double normalized = normalizePrice(adjusted);
        // Ensure price is valid (must be > 0 and have at most 2 decimal places)
        if (normalized <= 0) {
            normalized = price; // fallback
        }
        return normalized;
    }

    /**
     * Normalize price to valid tick size (0.01 for BTCUSDT futures)
     * Uses explicit decimal handling to avoid floating point errors
     */
    private double normalizePrice(double price) {
        if (price <= 0) return price;
        // Use BigDecimal for precise rounding to 2 decimal places
        java.math.BigDecimal bd = new java.math.BigDecimal(price).setScale(2, java.math.RoundingMode.HALF_UP);
        return bd.doubleValue();
    }

    private double calculateQuantity(CompositeSignal signal, double availableBalance, double price) {
        // Base quantity proportional to confidence
        double baseQty = 0.001 + signal.getConfidence() * 0.02;

        // Dynamic sizing based on available balance with leverage
        if (availableBalance > 0.1 && price > 0) {
            // With 20x leverage, use up to 80% of balance for margin
            // Max position value = availableBalance * 20
            // Max quantity = (availableBalance * 0.8) / price  (80% margin ratio)
            double maxFromBalance = (availableBalance * 0.8) / price;
            baseQty = Math.min(baseQty, maxFromBalance);
        }

        // Enforce minimum (0.001 BTC minimum on Binance)
        baseQty = Math.max(baseQty, 0.001);
        return normalizeQuantity(baseQty);
    }

    private List<Double> splitIfNeeded(double baseQty, ExecutionMode mode) {
        List<Double> quantities = new ArrayList<>();

        // High urgency or large orders get split
        if (mode == ExecutionMode.AGGRESSIVE && baseQty > 0.05) {
            // Split into 2-3 slices
            int slices = (int) Math.min(3, Math.max(2, baseQty / 0.03));
            double sliceQty = normalizeQuantity(baseQty / slices);
            for (int i = 0; i < slices; i++) {
                quantities.add(sliceQty);
            }
        } else {
            quantities.add(normalizeQuantity(baseQty));
        }

        return quantities;
    }

    /**
     * Normalize quantity to valid step size (0.001 for BTCUSDT futures)
     * Uses explicit decimal handling to avoid floating point errors
     */
    private double normalizeQuantity(double qty) {
        if (qty <= 0) return qty;
        // Use BigDecimal for precise rounding to 3 decimal places
        java.math.BigDecimal bd = new java.math.BigDecimal(qty).setScale(3, java.math.RoundingMode.HALF_UP);
        return bd.doubleValue();
    }
}
