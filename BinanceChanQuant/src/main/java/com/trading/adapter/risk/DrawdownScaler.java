package com.trading.adapter.risk;

/**
 * Drawdown-aware position scaler
 *
 * Scales position size based on current drawdown:
 * - 0-2% drawdown: 100% position
 * - 2-5% drawdown: 70% position
 * - 5-10% drawdown: 40% position
 * - 10-15% drawdown: 20% position
 * - >15% drawdown: 0% (no new positions)
 *
 * Refactored with:
 * - Configurable thresholds via constructor
 * - Sigmoid smoothing for boundary transitions
 * - Drawdown velocity tracking
 */
public class DrawdownScaler {

    // Drawdown thresholds - now configurable
    private final double ddWarning;
    private final double ddDanger;
    private final double ddCritical;
    private final double ddLimit;

    // Position scale factors
    private final double scaleWarning;
    private final double scaleDanger;
    private final double scaleCritical;
    private final double scaleBlock;

    // Drawdown velocity tracking
    private double lastDrawdown = 0.0;
    private long lastDrawdownTime = System.currentTimeMillis();
    private static final long VELOCITY_WINDOW_MS = 300_000; // 5 minutes

    public DrawdownScaler() {
        this(0.02, 0.05, 0.10, 0.15, 0.7, 0.4, 0.2, 0.0);
    }

    public DrawdownScaler(double ddWarning, double ddDanger, double ddCritical, double ddLimit,
                          double scaleWarning, double scaleDanger, double scaleCritical, double scaleBlock) {
        this.ddWarning = ddWarning;
        this.ddDanger = ddDanger;
        this.ddCritical = ddCritical;
        this.ddLimit = ddLimit;
        this.scaleWarning = scaleWarning;
        this.scaleDanger = scaleDanger;
        this.scaleCritical = scaleCritical;
        this.scaleBlock = scaleBlock;
    }

    /**
     * Calculate position scale factor based on drawdown using sigmoid smoothing
     * @param drawdown drawdown as a fraction (0.0 to 1.0)
     * @return scale factor from 0.0 to 1.0
     */
    public double scale(double drawdown) {
        // FIX: Use sigmoid smoothing at boundaries instead of step function
        // Calculate smoothed scale based on distance from each threshold

        double scale = 1.0;

        if (drawdown < ddWarning) {
            // Near warning threshold - use sigmoid transition
            double distFromWarning = ddWarning - drawdown;
            double sigmoidWidth = ddWarning * 0.3; // 30% of threshold as transition width
            scale = sigmoidInterpolate(drawdown, 0, ddWarning, 1.0, scaleWarning, sigmoidWidth);
        } else if (drawdown < ddDanger) {
            double distFromDanger = ddDanger - drawdown;
            double sigmoidWidth = (ddDanger - ddWarning) * 0.3;
            scale = sigmoidInterpolate(drawdown, ddWarning, ddDanger, scaleWarning, scaleDanger, sigmoidWidth);
        } else if (drawdown < ddCritical) {
            double distFromCritical = ddCritical - drawdown;
            double sigmoidWidth = (ddCritical - ddDanger) * 0.3;
            scale = sigmoidInterpolate(drawdown, ddDanger, ddCritical, scaleDanger, scaleCritical, sigmoidWidth);
        } else if (drawdown < ddLimit) {
            double distFromLimit = ddLimit - drawdown;
            double sigmoidWidth = (ddLimit - ddCritical) * 0.3;
            scale = sigmoidInterpolate(drawdown, ddCritical, ddLimit, scaleCritical, scaleBlock, sigmoidWidth);
        } else {
            scale = scaleBlock;
        }

        return Math.max(0.0, Math.min(1.0, scale));
    }

    /**
     * Sigmoid interpolation for smooth transitions at boundaries
     */
    private double sigmoidInterpolate(double x, double x1, double x2, double y1, double y2, double width) {
        // Normalize x to [0, 1] range
        double t = (x - x1) / (x2 - x1);
        // Sigmoid function centered at 0.5
        double sigmoid = 1.0 / (1.0 + Math.exp(-10 * (t - 0.5)));
        // Interpolate between y1 and y2
        return y1 + (y2 - y1) * sigmoid;
    }

    /**
     * Check if trading should be blocked entirely
     */
    public boolean isBlocked(double drawdown) {
        return drawdown >= ddLimit;
    }

    /**
     * Get description of current drawdown state
     */
    public String getState(double drawdown) {
        if (drawdown < ddWarning) return "NORMAL";
        if (drawdown < ddDanger) return "WARNING";
        if (drawdown < ddCritical) return "DANGER";
        if (drawdown < ddLimit) return "CRITICAL";
        return "BLOCKED";
    }

    /**
     * Get recommended max position as fraction of normal
     */
    public double getRecommendedPositionFraction(double drawdown) {
        return scale(drawdown);
    }

    /**
     * Calculate scaled position size
     */
    public double scalePosition(double basePosition, double drawdown) {
        return basePosition * scale(drawdown);
    }

    /**
     * Calculate drawdown velocity (change rate per minute)
     * FIX: Added velocity tracking to detect worsening/improving trends
     */
    public double getDrawdownVelocity(double currentDrawdown) {
        long now = System.currentTimeMillis();
        double velocity = 0.0;

        if (lastDrawdownTime > 0) {
            long elapsed = now - lastDrawdownTime;
            if (elapsed > 0) {
                double drawdownChange = currentDrawdown - lastDrawdown;
                // Convert to per-minute rate
                velocity = drawdownChange * (60_000.0 / elapsed);
            }
        }

        lastDrawdown = currentDrawdown;
        lastDrawdownTime = now;

        return velocity;
    }

    /**
     * Get configured thresholds for testing
     */
    public double getDdWarning() { return ddWarning; }
    public double getDdDanger() { return ddDanger; }
    public double getDdCritical() { return ddCritical; }
    public double getDdLimit() { return ddLimit; }
}
