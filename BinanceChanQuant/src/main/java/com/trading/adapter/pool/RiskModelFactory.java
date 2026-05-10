package com.trading.adapter.pool;

import com.trading.domain.signal.MarketContext;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.VolatilityRegime;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Factory for creating RiskModel from MarketContext
 *
 * Generates ATR-based stops adjusted for:
 * - Volatility regime (LOW/MEDIUM/HIGH/EXTREME)
 * - Trend regime (RANGE/TREND_UP/TREND_DOWN)
 * - Current market structure
 */
public class RiskModelFactory {

    /**
     * Build RiskModel for a new position
     *
     * @param entryPrice Entry price
     * @param positionSize Position size in base currency
     * @param direction LONG or SHORT
     * @param context Current market context (with ATR)
     * @return RiskModel with all stops calculated
     */
    public static RiskModel buildRiskModel(double entryPrice, double positionSize,
                                            TradeDirection direction, MarketContext context) {
        double atr = context != null ? context.getAtr() : entryPrice * 0.02;
        double atrPercent = context != null ? context.getAtrPercent() : 0.02;

        // Determine volatility regime
        String volRegime = determineVolatilityRegime(atrPercent);

        // Determine trend regime
        String trendRegime = context != null ? context.getRegime().name() : "RANGE";

        // ATR stop multiplier adjusted by regime
        double atrStopMultiplier = getAtrStopMultiplier(volRegime, trendRegime);

        // Take profit multiplier (higher than stop)
        double tpMultiplier = getTakeProfitMultiplier(volRegime, trendRegime);

        // Chandelier K adjusted by regime
        double chandelierK = getChandelierK(volRegime, trendRegime);

        RiskModel.Builder builder = RiskModel.builder()
            .atr(atr)
            .atrPercent(atrPercent)
            .entryPrice(entryPrice)
            .positionSize(positionSize)
            .direction(direction.name())
            .atrStopPercent(atrStopMultiplier)
            .takeProfitPercent(tpMultiplier)
            .chandelierExit(0)  // Calculated dynamically during trailing
            .volatilityRegime(volRegime)
            .trendRegime(trendRegime)
            .entryTime(System.currentTimeMillis())
            .maxHoldTimeMs(getMaxHoldTime(trendRegime))
            .trailingStopPercent(getTrailingStopPercent(volRegime))
            .trailingStartPercent(getTrailingStartPercent(volRegime))
            .maxLossPercent(5.0)  // Catastrophic stop -5%
            .liquidationBuffer(0.5);

        return builder.build();
    }

    /**
     * Determine volatility regime from ATR%
     */
    private static String determineVolatilityRegime(double atrPercent) {
        if (atrPercent > 0.05) {
            return "EXTREME";
        } else if (atrPercent > 0.03) {
            return "HIGH";
        } else if (atrPercent > 0.01) {
            return "MEDIUM";
        } else {
            return "LOW";
        }
    }

    /**
     * Get ATR stop multiplier based on regime
     *
     * Higher volatility = wider stop
     * Strong trend = tighter stop (follow the trend)
     *
     * Optimized: Wider stops to avoid premature stops
     */
    private static double getAtrStopMultiplier(String volatilityRegime, String trendRegime) {
        double base;

        switch (volatilityRegime) {
            case "EXTREME":
                base = 3.5;  // Very wide in extreme vol
                break;
            case "HIGH":
                base = 3.0;
                break;
            case "MEDIUM":
                base = 2.5;  // Wider than before
                break;
            case "LOW":
                base = 2.0;  // Wider than before (was 1.5)
                break;
            default:
                base = 2.5;
        }

        // In trends, use slightly wider stops to let position run
        if ("TREND_UP".equals(trendRegime) || "TREND_DOWN".equals(trendRegime)) {
            base *= 1.1;  // Slightly wider in trends
        }

        return base;
    }

    /**
     * Get take profit multiplier
     * Optimized: Higher TP to let winners run
     */
    private static double getTakeProfitMultiplier(String volatilityRegime, String trendRegime) {
        double base = getAtrStopMultiplier(volatilityRegime, trendRegime) * 2.0;  // Was 1.5x

        // In trends, let winners run significantly
        if ("TREND_UP".equals(trendRegime) || "TREND_DOWN".equals(trendRegime)) {
            base *= 1.5;  // Much higher TP in trends (was 1.2x)
        }

        return base;
    }

    /**
     * Get Chandelier K multiplier
     *
     * Chandelier Exit = HighestHigh - K * ATR (for LONG)
     * Optimized: Wider K to avoid premature trailing stops
     */
    private static double getChandelierK(String volatilityRegime, String trendRegime) {
        double base;

        switch (volatilityRegime) {
            case "EXTREME":
                base = 3.5;
                break;
            case "HIGH":
                base = 3.0;
                break;
            case "MEDIUM":
                base = 2.5;  // Was 2.0
                break;
            case "LOW":
                base = 2.0;  // Was 1.5
                break;
            default:
                base = 2.5;
        }

        // Wider in ranges, wider in trends (let winners run)
        if ("RANGE".equals(trendRegime)) {
            base *= 1.2;
        }
        if ("TREND_UP".equals(trendRegime) || "TREND_DOWN".equals(trendRegime)) {
            base *= 1.3;  // Wider in trends
        }

        return base;
    }

    /**
     * Get trailing stop percent based on volatility
     */
    private static double getTrailingStopPercent(String volatilityRegime) {
        switch (volatilityRegime) {
            case "EXTREME":
                return 3.0;
            case "HIGH":
                return 2.5;
            case "MEDIUM":
                return 2.0;
            case "LOW":
                return 1.5;
            default:
                return 2.0;
        }
    }

    /**
     * Get trailing start (profit needed before activating trailing)
     */
    private static double getTrailingStartPercent(String volatilityRegime) {
        switch (volatilityRegime) {
            case "EXTREME":
                return 2.0;
            case "HIGH":
                return 1.5;
            case "MEDIUM":
                return 1.0;
            case "LOW":
                return 0.5;
            default:
                return 1.0;
        }
    }

    /**
     * Get max hold time based on trend regime
     */
    private static long getMaxHoldTime(String trendRegime) {
        if ("TREND_UP".equals(trendRegime) || "TREND_DOWN".equals(trendRegime)) {
            return 60 * 60 * 1000;  // 60 min in trends
        } else {
            return 30 * 60 * 1000;  // 30 min in range
        }
    }

    /**
     * Update Chandelier exit price dynamically during position holding
     *
     * @param riskModel Current risk model
     * @param peakPrice Highest price since entry (for LONG)
     * @param lowestPrice Lowest price since entry (for SHORT)
     * @param atr Current ATR
     * @return Updated Chandelier exit price
     */
    public static double updateChandelierExit(RiskModel riskModel, double peakPrice, double lowestPrice, double atr) {
        String direction = riskModel.getDirection();
        String volRegime = riskModel.getVolatilityRegime();
        double k = getChandelierK(volRegime, riskModel.getTrendRegime());

        if ("LONG".equals(direction)) {
            return peakPrice - k * atr;
        } else {
            return lowestPrice + k * atr;
        }
    }
}