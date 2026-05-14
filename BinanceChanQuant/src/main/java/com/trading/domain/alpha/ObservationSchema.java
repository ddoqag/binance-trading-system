package com.trading.domain.alpha;

/**
 * Observation Schema Version
 *
 * Tracks evolution of trajectory observation model.
 * Critical for ensuring historical data remains comparable across schema changes.
 *
 * Version History:
 * - v1: Initial Alpha Temporal Dynamics Engine (Phase 2A)
 *       Core: AlphaHypothesis, AlphaTrajectoryRuntime, PnlSnapshot, TrajectoryMetrics
 * - v2: Observation Stabilization (Phase 2C)
 *       Added: DecayAttribution, halfLifeStdDev, halfLifeP50, halfLifeP90
 *       Changed: DecayCause now has probabilistic attribution (DecayAttribution)
 */
public final class ObservationSchema {

    public static final String SCHEMA_VERSION = "v2";
    public static final String TRAJECTORY_SCHEMA = "v1";
    public static final String DECAY_MODEL = "v2";
    public static final String SAMPLING_POLICY = "v1";
    public static final String ATTRIBUTION_MODEL = "v1";

    private ObservationSchema() {}

    /**
     * Semantic snapshot format for research-grade telemetry
     */
    public static final class SemanticSnapshot {
        public static final String FORMAT_VERSION = "v1";

        public static String format(TrajectoryMetrics m) {
            StringBuilder sb = new StringBuilder();
            sb.append("[AlphaTemporalSummary]\n");
            sb.append("schema=").append(SCHEMA_VERSION).append("\n");
            sb.append("alpha_id=").append(m.alphaId()).append("\n");
            sb.append("regime=").append(m.dominantRegime()).append("\n");
            sb.append("half_life_p50=").append(m.halfLifeP50Ms() / 1000.0).append("s\n");
            sb.append("half_life_p90=").append(m.halfLifeP90Ms() / 1000.0).append("s\n");
            sb.append("half_life_std=").append(m.halfLifeStdDevMs() / 1000.0).append("s\n");
            sb.append("mfe=").append(String.format("%.2f", m.mfe())).append("R\n");
            sb.append("mae=").append(String.format("%.2f", m.mae())).append("R\n");
            sb.append("mfe_mae_ratio=").append(String.format("%.2f", m.mfeMaeRatio())).append("\n");
            sb.append("realized=").append(String.format("%.2f", m.realizedPnl())).append("R\n");
            sb.append("decay_entropy=").append(m.attribution() != null
                ? String.format("%.2f", m.attribution().entropy()) : "N/A").append("\n");
            sb.append("decay_confidence=").append(m.attribution() != null
                ? String.format("%.2f", m.attribution().confidence()) : "N/A").append("\n");
            sb.append("dominant_decay=").append(m.decayCause()).append("\n");
            sb.append("reliability=").append(m.hasReliableHalfLife()).append("\n");
            sb.append("tradeable=").append(m.isTradeable()).append("\n");
            sb.append("persistent=").append(m.isPersistent()).append("\n");
            sb.append("structural_decay=").append(m.isStructuralDecay()).append("\n");
            if (m.attribution() != null && m.attribution().isMultiCausal()) {
                sb.append("multi_causal=true\n");
                for (var entry : m.attribution().contributingFactors().entrySet()) {
                    sb.append("  ").append(entry.getKey()).append("=")
                        .append(String.format("%.2f", entry.getValue())).append("\n");
                }
            }
            return sb.toString();
        }
    }
}