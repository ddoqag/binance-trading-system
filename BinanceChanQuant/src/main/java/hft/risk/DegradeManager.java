package hft.risk;

/**
 * DegradeManager - System Degradation Manager
 *
 * Implements V3-style degradation levels for system protection:
 * - Level 0: Normal operation
 * - Level 1: Reduced order rate
 * - Level 2: Block new orders, allow closes
 * - Level 3: Kill switch - block all orders
 *
 * Tracks error rates, drawdown, and system health.
 */
public class DegradeManager {
    public enum Level {
        NORMAL(0),
        WARNING(1),
        ELEVATED(2),
        CRITICAL(3),
        KILL(4);

        private final int value;
        Level(int value) { this.value = value; }
        public int value() { return value; }
    }

    private volatile Level currentLevel = Level.NORMAL;
    private volatile double maxPositionSize = 1.0;
    private volatile int maxOrderRate = 60;

    // Degradation triggers
    private volatile double errorRate = 0;
    private volatile double drawdown = 0;
    private volatile int circuitBreakerHits = 0;
    private volatile boolean wsConnected = true;

    // Configuration
    private final double maxDrawdown;
    private final int circuitBreakerThreshold;

    public DegradeManager(double maxDrawdown, int circuitBreakerThreshold) {
        this.maxDrawdown = maxDrawdown;
        this.circuitBreakerThreshold = circuitBreakerThreshold;
    }

    public static DegradeManager defaults() {
        return new DegradeManager(0.05, 5);  // 5% max drawdown, 5 errors to trigger
    }

    /**
     * Update system metrics and adjust degradation level
     */
    public void updateMetrics(double errorRate, double drawdown, int circuitBreakerHits, boolean wsConnected) {
        this.errorRate = errorRate;
        this.drawdown = drawdown;
        this.circuitBreakerHits = circuitBreakerHits;
        this.wsConnected = wsConnected;

        calculateLevel();
    }

    private void calculateLevel() {
        Level newLevel = Level.NORMAL;

        // Check circuit breaker
        if (circuitBreakerHits >= circuitBreakerThreshold) {
            newLevel = Level.KILL;
        }
        // Check drawdown
        else if (drawdown > maxDrawdown * 0.8) {
            newLevel = Level.CRITICAL;
        } else if (drawdown > maxDrawdown * 0.5) {
            newLevel = Level.ELEVATED;
        } else if (drawdown > maxDrawdown * 0.2) {
            newLevel = Level.WARNING;
        }
        // Check error rate
        else if (errorRate > 0.3) {
            newLevel = Level.ELEVATED;
        } else if (errorRate > 0.1) {
            newLevel = Level.WARNING;
        }
        // Check WebSocket
        else if (!wsConnected) {
            newLevel = Level.ELEVATED;
        }

        if (newLevel != currentLevel) {
            System.out.println("[DEGRADE] Level changed: " + currentLevel + " -> " + newLevel);
            currentLevel = newLevel;
            adjustLimits();
        }
    }

    private void adjustLimits() {
        switch (currentLevel) {
            case NORMAL:
                maxPositionSize = 1.0;
                maxOrderRate = 60;
                break;
            case WARNING:
                maxPositionSize = 0.8;
                maxOrderRate = 45;
                break;
            case ELEVATED:
                maxPositionSize = 0.5;
                maxOrderRate = 30;
                break;
            case CRITICAL:
                maxPositionSize = 0.2;
                maxOrderRate = 10;
                break;
            case KILL:
                maxPositionSize = 0;
                maxOrderRate = 0;
                break;
        }
    }

    /**
     * Check if trading is allowed
     */
    public boolean canTrade(boolean isClosing) {
        if (currentLevel == Level.KILL) {
            return false;
        }
        if (!isClosing && (currentLevel == Level.CRITICAL || currentLevel == Level.ELEVATED)) {
            return false;
        }
        return true;
    }

    /**
     * Get adjusted max position size based on current level
     */
    public double getMaxPositionSize(double baseMax) {
        return baseMax * maxPositionSize;
    }

    /**
     * Get max order rate
     */
    public int getMaxOrderRate() {
        return maxOrderRate;
    }

    public Level getCurrentLevel() {
        return currentLevel;
    }

    public double getErrorRate() {
        return errorRate;
    }

    public double getDrawdown() {
        return drawdown;
    }

    public int getCircuitBreakerHits() {
        return circuitBreakerHits;
    }

    public boolean isWsConnected() {
        return wsConnected;
    }
}
