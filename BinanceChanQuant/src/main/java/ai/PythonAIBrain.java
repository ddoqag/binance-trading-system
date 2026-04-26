package ai;

import hft.shm.V2SHMClient;

import java.util.concurrent.*;
import java.util.function.Consumer;

/**
 * PythonAIBrain - Bridge to Python AI Brain
 *
 * Runs Python v2_integrator.py as a subprocess and communicates
 * via shared memory (V2SHMClient).
 *
 * This allows the existing Python AI stack to work with the Java engine:
 * - Meta-Agent
 * - MoE (Mixture of Experts)
 * - SAC Agent
 */
public class PythonAIBrain {
    private Process process;
    private final String pythonPath;
    private final String integratorScript;
    private final V2SHMClient shmClient;

    private final ScheduledExecutorService heartbeat;
    private volatile boolean running = false;

    private Consumer<AISignal> onSignal;

    public PythonAIBrain(String pythonPath, String integratorScript, V2SHMClient shmClient) {
        this.pythonPath = pythonPath;
        this.integratorScript = integratorScript;
        this.shmClient = shmClient;
        this.heartbeat = Executors.newScheduledThreadPool(1);
    }

    /**
     * Start the Python AI brain subprocess
     */
    public void start() throws Exception {
        System.out.println("[AI] Starting Python AI Brain...");

        ProcessBuilder pb = new ProcessBuilder(
            pythonPath,
            integratorScript
        );

        pb.environment().put("HFT_SHM_PATH", shmClient.getPath());
        pb.environment().put("HFT_SYMBOL", "BTCUSDT");

        // Redirect output
        pb.redirectErrorStream(true);

        process = pb.start();
        running = true;

        // Start heartbeat monitor
        heartbeat.scheduleAtFixedRate(this::checkHeartbeat, 5, 5, TimeUnit.SECONDS);

        System.out.println("[AI] Python AI Brain started (PID: " + process.pid() + ")");
    }

    /**
     * Stop the Python AI brain
     */
    public void stop() {
        running = false;

        if (process != null && process.isAlive()) {
            process.destroy();
            try {
                process.waitFor(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                process.destroyForcibly();
            }
        }

        heartbeat.shutdown();
        System.out.println("[AI] Python AI Brain stopped");
    }

    /**
     * Check if Python process is alive
     */
    private void checkHeartbeat() {
        if (!running) return;

        if (process == null || !process.isAlive()) {
            System.err.println("[AI] Python AI Brain died, attempting restart...");
            try {
                Thread.sleep(1000);
                start();
            } catch (Exception e) {
                System.err.println("[AI] Restart failed: " + e.getMessage());
            }
        }
    }

    /**
     * Read AI signal from shared memory
     */
    public AISignal readSignal() {
        V2SHMClient.GlobalState gs = shmClient.readGlobalState();
        if (gs == null) return null;

        V2SHMClient.AIState ai = gs.ai;
        if (ai == null || ai.lastUpdateTs == 0) return null;

        return new AISignal(
            ai.direction,
            ai.confidence,
            ai.urgency,
            ai.sizeScale,
            ai.lastUpdateTs
        );
    }

    /**
     * Get shared memory client
     */
    public V2SHMClient getSHMClient() {
        return shmClient;
    }

    public boolean isRunning() {
        return running && process != null && process.isAlive();
    }

    public void setOnSignal(Consumer<AISignal> callback) {
        this.onSignal = callback;
    }

    /**
     * AI Signal from Python brain
     */
    public static class AISignal {
        public final double direction;   // -1.0=sell, +1.0=buy, 0.0=hold
        public final double confidence;  // 0.0~1.0
        public final double urgency;    // 0.0~1.0
        public final double sizeScale;  // 0.0~2.0
        public final long timestamp;    // Unix nanoseconds

        public AISignal(double direction, double confidence, double urgency,
                       double sizeScale, long timestamp) {
            this.direction = direction;
            this.confidence = confidence;
            this.urgency = urgency;
            this.sizeScale = sizeScale;
            this.timestamp = timestamp;
        }

        public boolean isHold() {
            return Math.abs(direction) < 0.1 || confidence < 0.15;
        }
    }

    private String getPath() {
        // This is a workaround - V2SHMClient doesn't expose path
        return "unknown";
    }
}
