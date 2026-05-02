package com.trading.messaging.messages;

import com.trading.messaging.Command;

/** Command to update risk state (PnL, position, etc). */
public class UpdateRiskStateCommand implements Command {
    private final double equity;
    private final double dailyPnl;
    private final double currentPosition;
    private final int dailyTrades;
    private final int dailyRejects;

    public UpdateRiskStateCommand(double equity, double dailyPnl, double currentPosition,
                                  int dailyTrades, int dailyRejects) {
        this.equity = equity;
        this.dailyPnl = dailyPnl;
        this.currentPosition = currentPosition;
        this.dailyTrades = dailyTrades;
        this.dailyRejects = dailyRejects;
    }

    @Override public String getMessageId() { return "UpdateRisk-" + System.nanoTime(); }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return "RiskActor"; }

    public double equity() { return equity; }
    public double dailyPnl() { return dailyPnl; }
    public double currentPosition() { return currentPosition; }
    public int dailyTrades() { return dailyTrades; }
    public int dailyRejects() { return dailyRejects; }
}
