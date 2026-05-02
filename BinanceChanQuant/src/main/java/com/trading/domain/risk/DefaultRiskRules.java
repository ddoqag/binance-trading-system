package com.trading.domain.risk;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Default Rules Factory - creates standard risk rule set.
 */
public final class DefaultRiskRules {

    private DefaultRiskRules() {}  // Utility class

    /**
     * Create default rules engine with standard configuration.
     */
    public static RulesEngine createDefault() {
        return createDefault(
            10.0,      // maxPosition
            10000.0,   // maxDailyLoss
            120,       // maxOrdersPerMinute
            1000000.0  // maxOrderValue
        );
    }

    /**
     * Create with custom parameters.
     */
    public static RulesEngine createDefault(
        double maxPosition,
        double maxDailyLoss,
        int maxOrdersPerMinute,
        double maxOrderValue
    ) {
        RulesEngine engine = new RulesEngine();

        // Add rules in priority order (highest first)
        engine.addRule(new RateLimitRule(maxOrdersPerMinute));

        AtomicReference<Double> positionRef = new AtomicReference<>(0.0);
        engine.addRule(new MaxPositionRule(maxPosition));

        AtomicReference<Double> pnlRef = new AtomicReference<>(0.0);
        engine.addRule(new DailyLossLimitRule(maxDailyLoss));

        engine.addRule(new MarginCheckRule(maxOrderValue));

        return engine;
    }

    /**
     * Create rules for paper trading (relaxed limits).
     */
    public static RulesEngine createPaperTrading() {
        RulesEngine engine = new RulesEngine();

        engine.addRule(new RateLimitRule(240));  // Double for paper
        engine.addRule(new MaxPositionRule(20.0));  // 2x normal
        engine.addRule(new DailyLossLimitRule(20000.0));  // 2x normal
        engine.addRule(new MarginCheckRule(2000000.0));  // 2x normal

        return engine;
    }
}