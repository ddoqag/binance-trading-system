package com.trading.domain.signal;

import com.trading.domain.signal.ConfidenceVelocity;
import com.trading.domain.signal.AlphaHalfLife;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Confidence Velocity and Alpha Half-Life Tests (P3)
 */
@DisplayName("P3 Temporal Modeling Tests")
public class ConfidenceVelocityTest {

    // ========== ConfidenceVelocity Tests ==========

    @Test
    @DisplayName("STABLE velocity when confidence unchanged")
    void stableVelocity() {
        // 0.7 confidence, no change over 10 minutes
        ConfidenceVelocity cv = new ConfidenceVelocity(0.7, 0.0, 0.0, 10);

        assertEquals(ConfidenceVelocity.VelocityGrade.STABLE, cv.grade());
        assertTrue(cv.isStable());
        assertFalse(cv.isRapid());
    }

    @Test
    @DisplayName("GRADUAL velocity for normal decay")
    void gradualDecay() {
        // -0.02 per minute (2% drop per minute)
        ConfidenceVelocity cv = new ConfidenceVelocity(0.5, -0.02, 0.0, 5);

        assertEquals(ConfidenceVelocity.VelocityGrade.GRADUAL, cv.grade());
        assertTrue(cv.halfLifeSeconds() > 0);
    }

    @Test
    @DisplayName("EXTREME velocity for rapid decay")
    void extremeVelocity() {
        // -0.2 per minute (extreme drop)
        ConfidenceVelocity cv = new ConfidenceVelocity(0.72, -0.2, -0.05, 1);

        assertEquals(ConfidenceVelocity.VelocityGrade.EXTREME, cv.grade());
        assertTrue(cv.isExtreme());
        assertTrue(cv.expectedRemainingSeconds() < 300);  // Less than 5 min
    }

    @Test
    @DisplayName("RAPID velocity for concerning decay")
    void rapidVelocity() {
        // -0.10 per minute
        ConfidenceVelocity cv = new ConfidenceVelocity(0.4, -0.10, -0.02, 2);

        assertTrue(cv.isRapid());
        assertEquals(ConfidenceVelocity.VelocityGrade.RAPID, cv.grade());
    }

    @Test
    @DisplayName("Minutes to reach threshold calculation")
    void minutesToThreshold() {
        ConfidenceVelocity cv = new ConfidenceVelocity(0.6, -0.03, 0, 5);

        double minutesTo25 = cv.minutesToReach(0.25);
        assertTrue(minutesTo25 > 5);  // Should take more than 5 min
        assertTrue(minutesTo25 < 20); // But less than 20 min
    }

    @Test
    @DisplayName("Half-life calculation")
    void halfLifeCalculation() {
        // At -0.05 per minute, half-life should be around 14 min
        // halfLife = ln(2) / |v| * current = 0.693 / 0.05 * 0.6 ≈ 8.3 min
        ConfidenceVelocity cv = new ConfidenceVelocity(0.6, -0.05, 0, 3);

        assertTrue(cv.halfLifeSeconds() > 0);
        assertTrue(cv.halfLifeSeconds() < 600); // Less than 10 min
    }

    @Test
    @DisplayName("Extreme decay means immediate action")
    void extremeMeansImmediate() {
        // 0.72 → 0.18 in 2 bars = extreme velocity
        ConfidenceVelocity cv = new ConfidenceVelocity(0.18, -0.27, -0.05, 2);

        assertTrue(cv.isExtreme());
        assertTrue(cv.shouldActNow());  // Less than 5 min remaining
    }

    @Test
    @DisplayName("Velocity with no decay")
    void noDecay() {
        ConfidenceVelocity cv = new ConfidenceVelocity(0.5, 0.01, 0, 10);

        assertEquals(Double.MAX_VALUE, cv.expectedRemainingSeconds(), 0.01);
        assertFalse(cv.isRapid());
    }

    // ========== AlphaHalfLife Tests ==========

    @Test
    @DisplayName("LONG_LIVED in trending regime")
    void longLivedInTrend() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.7, "TREND_UP", 0.005);  // Low vol

        assertEquals(AlphaHalfLife.LifeGrade.LONG_LIVED, hl.grade());
        assertTrue(hl.halfLifeSeconds() > 900);
        assertTrue(hl.isReliable());
    }

    @Test
    @DisplayName("TRANSIENT in high volatility regime")
    void transientInHighVol() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.6, "HIGH_VOL", 0.05);

        assertEquals(AlphaHalfLife.LifeGrade.TRANSIENT, hl.grade());
        assertTrue(hl.halfLifeSeconds() < 300);
        assertTrue(hl.shouldActNow());
    }

    @Test
    @DisplayName("MEDIUM_LIFE in range regime")
    void mediumLifeInRange() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.65, "RANGE", 0.015);

        assertEquals(AlphaHalfLife.LifeGrade.MEDIUM_LIFE, hl.grade());
        assertTrue(hl.halfLifeSeconds() > 400 && hl.halfLifeSeconds() < 1000);
    }

    @Test
    @DisplayName("Execution urgency multiplier for short half-life")
    void executionUrgencyForShort() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.6, "HIGH_VOL", 0.06);

        assertTrue(hl.executionUrgencyMultiplier() > 1.0);
        assertTrue(hl.sizeMultiplier() < 1.0);
    }

    @Test
    @DisplayName("Execution urgency multiplier for long half-life")
    void executionUrgencyForLong() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.7, "TREND_UP", 0.005);  // Very low vol

        // With 0.005 vol (< 0.01), volFactor = 1.5, baseHL = 900, adjusted = 1350 (> 900)
        assertTrue(hl.executionUrgencyMultiplier() < 1.0);
        assertEquals(1.0, hl.sizeMultiplier(), 0.01);
    }

    @Test
    @DisplayName("Size multiplier decreases as half-life shrinks")
    void sizeMultiplierDecreases() {
        // longLife: HL = 1350 (volFactor 1.5) → sizeMultiplier = 1.0
        AlphaHalfLife longLife = AlphaHalfLife.fromRegime(0.7, "TREND_UP", 0.005);

        // shortLife: HL = 38.5 (< 60) → TRANSIENT, sizeMultiplier = 0.5
        AlphaHalfLife shortLife = AlphaHalfLife.withCurrentConfidence(180, 0.15, 0.7, "HIGH_VOL");

        assertTrue(longLife.sizeMultiplier() > shortLife.sizeMultiplier(),
            "longLife(" + longLife.sizeMultiplier() + ") should be > shortLife(" + shortLife.sizeMultiplier() + ")");
        assertEquals(1.0, longLife.sizeMultiplier(), 0.01);
        // TRANSIENT (HL < 60): sizeMultiplier = 0.5
        assertTrue(shortLife.sizeMultiplier() < 0.6);
    }

    @Test
    @DisplayName("Reliability based on coefficient of variation")
    void reliabilityBasedOnCV() {
        // From regime factory, halfLifeStdDev = 0.3 * halfLife
        // CV = 0.3 / 1.0 = 0.3 < 0.5 = reliable
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.7, "RANGE", 0.02);

        assertTrue(hl.isReliable());
    }

    @Test
    @DisplayName("P90 is higher than P50")
    void p90HigherThanP50() {
        AlphaHalfLife hl = AlphaHalfLife.fromRegime(0.6, "RANGE", 0.02);

        assertTrue(hl.p90() >= hl.p50());
    }

    @Test
    @DisplayName("DYING grade for very short half-life")
    void dyingGrade() {
        // Use withCurrentConfidence to create very short half-life
        AlphaHalfLife hl = AlphaHalfLife.withCurrentConfidence(180, 0.15, 0.7, "HIGH_VOL");

        // 180 * (0.15/0.7) = 38.5 seconds → DYING (< 60)
        assertEquals(AlphaHalfLife.LifeGrade.DYING, hl.grade());
        assertTrue(hl.halfLifeSeconds() < 60);
    }

    @Test
    @DisplayName("isTransient for SHORT_LIFE or TRANSIENT grades")
    void isTransientCheck() {
        AlphaHalfLife shortLife = AlphaHalfLife.fromRegime(0.6, "HIGH_VOL", 0.05);
        AlphaHalfLife dying = AlphaHalfLife.fromRegime(0.3, "HIGH_VOL", 0.08);

        assertTrue(shortLife.isTransient());
        assertTrue(dying.isTransient());
    }

    @Override
    public String toString() {
        return "ConfidenceVelocityTest";
    }
}