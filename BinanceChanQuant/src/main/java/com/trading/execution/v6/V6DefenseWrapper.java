package com.trading.execution.v6;

import hft.defense.DefenseFSM;

/**
 * V6防御系统封装
 * 将HFT DefenseFSM集成到V6架构
 *
 * 集成方式：
 * 1. 在信号处理前调用checkSignal()进行防御检查
 * 2. 在成交后调用recordTrade()记录胜负
 * 3. 在紧急情况调用kill()停止所有交易
 */
public class V6DefenseWrapper {

    private final DefenseFSM defenseFSM;

    public V6DefenseWrapper() {
        this.defenseFSM = DefenseFSM.defaults();
    }

    public V6DefenseWrapper(int maxConsecutiveLosses, double toxicityThreshold) {
        this.defenseFSM = new DefenseFSM(maxConsecutiveLosses, toxicityThreshold);
    }

    /**
     * 信号处理前的防御检查
     * @param currentPos 当前持仓
     * @param signalDir 信号方向 (1=LONG, -1=SHORT, 0=NEUTRAL)
     * @param toxicityScore 市场毒性评分 (0-1)
     * @return 防御结果
     */
    public DefenseResult checkSignal(double currentPos, int signalDir, double toxicityScore) {
        // 更新防御状态
        defenseFSM.update(toxicityScore, defenseFSM.getConsecutiveLosses(), currentPos != 0);

        // 检查是否允许开仓
        if (!defenseFSM.allowNewOrders()) {
            return new DefenseResult(false, 0, "DefenseFSM: new orders blocked by state " + defenseFSM.getCurrentState());
        }

        // 检查是否允许增加仓位
        if (signalDir > 0 && currentPos > 0 && !defenseFSM.allowPositionIncrease()) {
            return new DefenseResult(false, 0, "DefenseFSM: position increase blocked by state " + defenseFSM.getCurrentState());
        }

        // 获取仓位缩放因子
        double scale = defenseFSM.getPositionScale();

        // 检查是否应该平仓
        if (defenseFSM.shouldClosePositions() && Math.abs(currentPos) > 1e-6) {
            System.out.printf("[V6-Defense] Should close: state=%s, currentPos=%.4f%n",
                defenseFSM.getCurrentState(), currentPos);
            return new DefenseResult(true, -currentPos, scale, "DefenseFSM: closing all positions");
        }

        // 检查是否应该缩仓
        if (defenseFSM.shouldReducePositions() && Math.abs(currentPos) > 1e-6) {
            double target = currentPos * scale;
            double delta = target - currentPos;
            if (Math.abs(delta) > 1e-6) {
                System.out.printf("[V6-Defense] Reducing: state=%s, scale=%.2f, currentPos=%.4f -> %.4f%n",
                    defenseFSM.getCurrentState(), scale, currentPos, target);
                return new DefenseResult(true, delta, scale, "DefenseFSM: reducing position");
            }
        }

        return new DefenseResult(true, 0, scale, "OK");
    }

    /**
     * 简化版检查（不更新toxicity）
     */
    public DefenseResult checkSignal(double currentPos, int signalDir) {
        return checkSignal(currentPos, signalDir, defenseFSM.getToxicityScore());
    }

    /**
     * 记录交易结果
     */
    public void recordTrade(double pnl) {
        if (pnl < 0) {
            defenseFSM.recordLoss();
            System.out.printf("[V6-Defense] Loss recorded: consecutiveLosses=%d, state=%s%n",
                defenseFSM.getConsecutiveLosses(), defenseFSM.getCurrentState());
        } else {
            defenseFSM.recordWin();
            if (defenseFSM.getConsecutiveLosses() == 0) {
                System.out.printf("[V6-Defense] Win recorded: state=%s%n",
                    defenseFSM.getCurrentState());
            }
        }
    }

    /**
     * 更新毒性评分
     */
    public void updateToxicity(double toxicityScore) {
        defenseFSM.update(toxicityScore, defenseFSM.getConsecutiveLosses(),
            getPosition() != 0);
    }

    /**
     * 紧急停止
     */
    public void kill() {
        defenseFSM.kill();
        System.err.printf("[V6-Defense] ⚠️ KILL activated - all trading stopped%n");
    }

    /**
     * 获取当前防御状态
     */
    public DefenseFSM.State getState() {
        return defenseFSM.getCurrentState();
    }

    /**
     * 获取仓位缩放因子
     */
    public double getPositionScale() {
        return defenseFSM.getPositionScale();
    }

    /**
     * 是否允许新订单
     */
    public boolean allowNewOrders() {
        return defenseFSM.allowNewOrders();
    }

    /**
     * 是否应该关闭所有仓位
     */
    public boolean shouldCloseAll() {
        return defenseFSM.shouldClosePositions();
    }

    private double getPosition() {
        return 0; // 由调用方提供
    }

    /**
     * 防御结果
     */
    public static class DefenseResult {
        public final boolean allowed;          // 是否允许
        public final double adjustedDelta;      // 调整后的delta（用于平仓或缩仓）
        public final double sizeScale;         // 仓位缩放因子
        public final String reason;            // 原因描述

        public DefenseResult(boolean allowed, double adjustedDelta, double sizeScale, String reason) {
            this.allowed = allowed;
            this.adjustedDelta = adjustedDelta;
            this.sizeScale = sizeScale;
            this.reason = reason;
        }

        // 简化构造（没有sizeScale）
        public DefenseResult(boolean allowed, double adjustedDelta, String reason) {
            this(allowed, adjustedDelta, 1.0, reason);
        }

        public boolean needsImmediateClose() {
            return allowed && Math.abs(adjustedDelta) > 1e-6 && adjustedDelta == -adjustedDelta;
        }
    }
}
