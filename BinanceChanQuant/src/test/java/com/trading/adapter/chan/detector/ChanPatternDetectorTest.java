package com.trading.adapter.chan.detector;

import com.trading.adapter.chan.detector.ChanPatternDetector.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

class ChanPatternDetectorTest {

    @Test
    @DisplayName("PatternSignal.none() should return NONE signal")
    void patternSignalNoneShouldReturnNone() {
        PatternSignal signal = PatternSignal.none();
        assertEquals(SignalType.NONE, signal.type);
        assertEquals(0, signal.confidence);
        assertFalse(signal.hasSignal());
    }

    @Test
    @DisplayName("hasSignal should return true only for valid signals")
    void hasSignalShouldReturnTrueOnlyForValidSignals() {
        PatternSignal noneSignal = PatternSignal.none();
        assertFalse(noneSignal.hasSignal());

        PatternSignal validSignal = new PatternSignal(SignalType.BUY_1, 0.6, 100.0, System.currentTimeMillis(), "test");
        assertTrue(validSignal.hasSignal());

        PatternSignal zeroConfidenceSignal = new PatternSignal(SignalType.BUY_1, 0, 100.0, System.currentTimeMillis(), "test");
        assertFalse(zeroConfidenceSignal.hasSignal());
    }

    @Test
    @DisplayName("SignalType enum should have all expected values")
    void signalTypeEnumShouldHaveAllExpectedValues() {
        assertNotNull(SignalType.BUY_1);
        assertNotNull(SignalType.SELL_1);
        assertNotNull(SignalType.BUY_2);
        assertNotNull(SignalType.SELL_2);
        assertNotNull(SignalType.BUY_3);
        assertNotNull(SignalType.SELL_3);
        assertNotNull(SignalType.RANGE_BOUND);
        assertNotNull(SignalType.RESONANCE_BUY);
        assertNotNull(SignalType.RESONANCE_SELL);
        assertNotNull(SignalType.NONE);
    }
}
