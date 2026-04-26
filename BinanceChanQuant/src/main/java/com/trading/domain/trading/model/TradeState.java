package com.trading.domain.trading.model;

/**
 * Trade State - Position tracking
 * Note: This is a mutable singleton - not thread-safe for concurrent execution
 */
public class TradeState {
    private static String position = "NONE";
    private static double positionQty = 0.0;

    public static final double STOP_LOSS_RATE = 0.02;
    public static final double MAX_POS_RATIO = 0.30;

    public static String getPosition() { return position; }
    public static void setPosition(String p) { position = p; }

    public static double getPositionQty() { return positionQty; }
    public static void setPositionQty(double qty) { positionQty = qty; }
}
