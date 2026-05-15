package com.trading.domain.trading.model;

/**
 * ZeroRiskModel - Null Object Pattern for RiskModel
 *
 * Used for empty positions to prevent NPE in lifecycle checks.
 * All stop methods return safe "not triggered" values.
 *
 * Key principle: An empty position has no risk exposure,
 * so no stop should ever trigger.
 */
public final class ZeroRiskModel extends RiskModel {

    public static final ZeroRiskModel INSTANCE = new ZeroRiskModel();

    private ZeroRiskModel() {
        super(new Builder());
    }

    @Override
    public double getAtr() { return 0.0; }

    @Override
    public double getAtrPercent() { return 0.0; }

    @Override
    public double getEntryPrice() { return 0.0; }

    @Override
    public double getPositionSize() { return 0.0; }

    @Override
    public String getDirection() { return "NONE"; }

    @Override
    public double getAtrStopPrice() { return 0.0; }

    @Override
    public double getAtrStopPercent() { return 0.0; }

    @Override
    public double getStructureStopPrice() { return 0.0; }

    @Override
    public double getChandelierExit() { return 0.0; }

    @Override
    public double getTakeProfitPrice() { return 0.0; }

    @Override
    public double getTakeProfitPercent() { return 0.0; }

    @Override
    public double getLiquidationBuffer() { return 0.0; }

    @Override
    public double getMaxLossPercent() { return 100.0; } // Never trigger

    @Override
    public double getTrailingStopPercent() { return 0.0; }

    @Override
    public double getTrailingStartPercent() { return 0.0; }

    @Override
    public String getVolatilityRegime() { return "NONE"; }

    @Override
    public String getTrendRegime() { return "NONE"; }

    @Override
    public long getEntryTime() { return 0; }

    @Override
    public long getMaxHoldTimeMs() { return 0; }

    @Override
    public boolean isAtrStopHit(double currentPrice) { return false; }

    @Override
    public boolean isStructureStopHit(double currentPrice) { return false; }

    @Override
    public boolean isChandelierStopHit(double highestPrice, double currentPrice) { return false; }

    @Override
    public boolean isCatastrophicStopHit(double unrealizedPnlPercent) { return false; }

    @Override
    public boolean isTakeProfitHit(double currentPrice) { return false; }

    @Override
    public double calculateDrawdownFromPeak(double currentPrice, double peakPrice) { return 0.0; }

    @Override
    public double getStopDistance() { return 0.0; }

    @Override
    public double getRiskRewardRatio(double targetPrice) { return 0.0; }

    @Override
    public String toString() {
        return "ZeroRiskModel{EMPTY_POSITION}";
    }
}