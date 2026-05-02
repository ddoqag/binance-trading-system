package com.trading.domain.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.risk.RiskCheckResult;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Rules Engine - executes risk rules in priority order.
 * Stops at first rejection (fail-fast).
 */
public class RulesEngine {

    private final List<RiskRule> rules = new ArrayList<>();

    public RulesEngine() {}

    public RulesEngine(List<RiskRule> rules) {
        this.rules.addAll(rules);
        sortByPriority();
    }

    public void addRule(RiskRule rule) {
        rules.add(rule);
        sortByPriority();
    }

    public void removeRule(String name) {
        rules.removeIf(r -> r.getName().equals(name));
    }

    public void clearRules() {
        rules.clear();
    }

    /**
     * Run all enabled rules in priority order.
     * Stops at first rejection.
     */
    public RiskCheckResult check(Order order) {
        for (RiskRule rule : rules) {
            if (!rule.isEnabled()) continue;

            RiskRule.CheckResult result = rule.check(order);
            if (result.isRejected()) {
                return RiskCheckResult.reject(
                    "Rule " + rule.getName() + " rejected: " + result.getReason(),
                    result.getCode() != null ? result.getCode() : "RULE_REJECTED"
                );
            }
        }
        return RiskCheckResult.allow();
    }

    /**
     * Check all rules and return all failures.
     */
    public List<RiskRule.CheckResult> checkAll(Order order) {
        List<RiskRule.CheckResult> results = new ArrayList<>();
        for (RiskRule rule : rules) {
            if (!rule.isEnabled()) continue;
            RiskRule.CheckResult result = rule.check(order);
            results.add(result);
        }
        return results;
    }

    public List<RiskRule> getRules() {
        return new ArrayList<>(rules);
    }

    private void sortByPriority() {
        rules.sort(Comparator.comparingInt(RiskRule::getPriority).reversed());
    }
}