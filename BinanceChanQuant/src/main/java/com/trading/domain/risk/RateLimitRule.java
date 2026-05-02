package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Rate Limit Rule - enforces maximum orders per minute.
 */
public class RateLimitRule implements RiskRule {

    private final String name;
    private final int maxOrdersPerMinute;
    private final AtomicInteger ordersThisMinute;
    private final AtomicLong lastResetTime;

    public RateLimitRule(int maxOrdersPerMinute) {
        this("RateLimit", maxOrdersPerMinute, new AtomicInteger(0), new AtomicLong(System.currentTimeMillis()));
    }

    public RateLimitRule(String name, int maxOrdersPerMinute, AtomicInteger ordersThisMinute, AtomicLong lastResetTime) {
        this.name = name;
        this.maxOrdersPerMinute = maxOrdersPerMinute;
        this.ordersThisMinute = ordersThisMinute;
        this.lastResetTime = lastResetTime;
    }

    @Override
    public String getName() {
        return name;
    }

    @Override
    public CheckResult check(Order order) {
        resetIfNeeded();

        if (ordersThisMinute.get() >= maxOrdersPerMinute) {
            return CheckResult.reject(
                "Rate limit exceeded: " + ordersThisMinute.get() + " orders this minute, max " + maxOrdersPerMinute,
                "RATE_LIMIT_EXCEEDED"
            );
        }

        ordersThisMinute.incrementAndGet();
        return CheckResult.pass();
    }

    @Override
    public int getPriority() {
        return 200;  // Highest priority - rate limit should be checked first
    }

    private void resetIfNeeded() {
        long now = System.currentTimeMillis();
        if (now - lastResetTime.get() > 60_000) {
            ordersThisMinute.set(0);
            lastResetTime.set(now);
        }
    }

    public int getCount() {
        return ordersThisMinute.get();
    }
}