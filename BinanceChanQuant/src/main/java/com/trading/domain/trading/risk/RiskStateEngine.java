package com.trading.domain.trading.risk;

/**
 * RiskStateEngine - 风险状态机引擎
 * 根据 drawdown 和 exposureRatio 计算当前风险状态
 */
public class RiskStateEngine {

    private final double cautionDrawdown;   // -0.02 = 2%回撤触发CAUTION
    private final double killDrawdown;       // -0.05 = 5%回撤触发KILL
    private final double cautionExposure;     // 0.7 = 70%仓位暴露触发CAUTION
    private final double killExposure;      // 0.9 = 90%仓位暴露触发KILL

    public RiskStateEngine(double cautionDrawdown, double killDrawdown,
                          double cautionExposure, double killExposure) {
        this.cautionDrawdown = cautionDrawdown;
        this.killDrawdown = killDrawdown;
        this.cautionExposure = cautionExposure;
        this.killExposure = killExposure;
    }

    public RiskStateEngine() {
        this(-0.02, -0.05, 0.7, 0.9);
    }

    public RiskState evaluate(double drawdown, double exposureRatio) {
        // KILL 状态优先判断
        if (drawdown <= killDrawdown || exposureRatio >= killExposure) {
            return RiskState.KILL;
        }

        // CAUTION 状态
        if (drawdown <= cautionDrawdown || exposureRatio >= cautionExposure) {
            return RiskState.CAUTION;
        }

        return RiskState.NORMAL;
    }

    public RiskState evaluate(double drawdown, double exposureRatio, double unrealizedPnl, double maxUnrealizedLoss) {
        // 额外判断：浮亏超限也进入CAUTION
        if (unrealizedPnl < maxUnrealizedLoss) {
            return RiskState.CAUTION;
        }

        return evaluate(drawdown, exposureRatio);
    }
}
