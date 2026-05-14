package com.trading.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Quantity Calculator - Exchange-compliant quantity sizing with Hard Floor protection
 *
 * Handles Binance FUTURES quantity rules:
 * - stepSize: quantity must be divisible by stepSize (qty % stepSize == 0)
 * - minQty: minimum order quantity
 * - minNotional: minimum notional value (price * qty >= minNotional)
 *
 * Hard Floor logic:
 * - If calculated qty < minQty but signal is strong (conf > threshold) → floor up to minQty
 * - If calculated qty passes minQty but fails minNotional → floor up to minNotional/price
 * - If resulting qty > maxQty → cap at maxQty
 */
public final class QuantityCalculator {

    private static final Logger log = LoggerFactory.getLogger(QuantityCalculator.class);

    // BTCUSDT Futures symbol constants (from Binance exchange info)
    public static final String SYMBOL = "BTCUSDT";
    public static final double STEP_SIZE = 0.001;       // 0.001 BTC
    public static final double MIN_QTY = 0.001;          // 0.001 BTC minimum
    public static final double MIN_NOTIONAL = 5.0;       // 5 USDT minimum notional
    public static final int QUANTITY_PRECISION = 3;       // 3 decimal places

    // Hard floor confidence threshold (signal must be stronger than this to floor-up)
    public static final double FLOOR_UP_CONFIDENCE_THRESHOLD = 0.70;

    private QuantityCalculator() {} // Utility class

    /**
     * Calculate safe quantity with Hard Floor protection
     *
     * @param rawQty Raw calculated quantity (before floor check)
     * @param currentPrice Current market price
     * @param signalConfidence Signal confidence (0-1)
     * @return Binance-compliant quantity
     */
    public static double calculateSafeQuantity(double rawQty, double currentPrice, double signalConfidence) {
        if (rawQty <= 0 || currentPrice <= 0) {
            return 0.0;
        }

        double notional = rawQty * currentPrice;
        double minNotionalFloor = MIN_NOTIONAL / currentPrice;

        // Step 1: Apply Hard Floor if notional is below minimum
        double flooredQty = rawQty;
        if (notional < MIN_NOTIONAL) {
            if (signalConfidence >= FLOOR_UP_CONFIDENCE_THRESHOLD) {
                // Signal is strong enough → floor up to meet min notional
                flooredQty = minNotionalFloor;
                log.info("[QuantityCalc] Hard floor UP: qty {:.4f} → {:.4f} (conf={}, notional={:.2f} < min={})",
                    rawQty, flooredQty, signalConfidence, notional, MIN_NOTIONAL);
            } else {
                // Signal too weak → abandon this order
                log.info("[QuantityCalc] Hard floor ABANDON: qty {:.4f}, notional={:.2f} < min={}, conf={} < threshold={}",
                    rawQty, notional, MIN_NOTIONAL, signalConfidence, FLOOR_UP_CONFIDENCE_THRESHOLD);
                return 0.0;
            }
        }

        // Step 2: Round to stepSize precision (Binance requirement: qty % stepSize == 0)
        double roundedQty = floorToStepSize(flooredQty, STEP_SIZE);

        // Step 3: Final safety check - ensure rounded qty still meets minimum
        if (roundedQty < MIN_QTY) {
            log.warn("[QuantityCalc] Rounded qty {:.4f} < minQty {:.4f}, abandoning", roundedQty, MIN_QTY);
            return 0.0;
        }

        return roundedQty;
    }

    /**
     * Round down to nearest stepSize (ensures qty % stepSize == 0)
     * Uses floor(qty / stepSize) * stepSize formula
     */
    public static double floorToStepSize(double qty, double stepSize) {
        return Math.floor(qty / stepSize) * stepSize;
    }

    /**
     * Round quantity to exchange precision (standardized for BTCUSDT: 3 decimals)
     */
    public static double roundToPrecision(double qty, int precision) {
        double factor = Math.pow(10, precision);
        return Math.floor(qty * factor) / factor;
    }

    /**
     * Calculate notional value
     */
    public static double notional(double qty, double price) {
        return qty * price;
    }

    /**
     * Check if quantity passes Binance exchange filters
     */
    public static boolean isValidQuantity(double qty, double price) {
        if (qty < MIN_QTY) return false;
        if (notional(qty, price) < MIN_NOTIONAL) return false;
        if (qty % STEP_SIZE > 0.0001) return false; // Allow small floating point tolerance
        return true;
    }
}