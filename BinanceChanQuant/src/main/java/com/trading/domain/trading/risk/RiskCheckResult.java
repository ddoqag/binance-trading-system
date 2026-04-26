package com.trading.domain.trading.risk;

/**
 * Risk Check Result
 */
public class RiskCheckResult {
    private final boolean allowed;
    private final String message;
    private final String ruleTriggered;
    private double suggestedQuantity = 0.0;

    private RiskCheckResult(boolean allowed, String message, String ruleTriggered) {
        this.allowed = allowed;
        this.message = message;
        this.ruleTriggered = ruleTriggered;
    }

    public static RiskCheckResult allow() {
        return new RiskCheckResult(true, "", "");
    }

    public static RiskCheckResult reject(String message, String ruleTriggered) {
        return new RiskCheckResult(false, message, ruleTriggered);
    }

    public boolean isAllowed() { return allowed; }
    public String getMessage() { return message; }
    public String getRuleTriggered() { return ruleTriggered; }
    public double getSuggestedQuantity() { return suggestedQuantity; }
    public void setSuggestedQuantity(double q) { this.suggestedQuantity = q; }
}
