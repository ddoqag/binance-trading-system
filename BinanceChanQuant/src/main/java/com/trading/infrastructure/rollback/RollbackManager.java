package com.trading.infrastructure.rollback;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Supplier;

/**
 * 回滚管理器 - 检查点注册 + 动态回滚 + 状态保存
 */
public class RollbackManager {

    private static final Logger log = LoggerFactory.getLogger(RollbackManager.class);
    private static volatile RollbackManager instance;

    // 检查点栈 - key: 检查点名称, value: 回滚动作
    private final ConcurrentHashMap<String, Deque<Checkpoint>> checkpoints = new ConcurrentHashMap<>();

    // 当前活跃的检查点名称
    private final ThreadLocal<Deque<String>> activeCheckpoints = ThreadLocal.withInitial(LinkedList::new);

    // 状态存储 - key: 状态名称, value: 状态快照
    private final ConcurrentHashMap<String, StateSnapshot> stateSnapshots = new ConcurrentHashMap<>();

    // 事件监听器
    private final List<RollbackListener> listeners = new CopyOnWriteArrayList<>();

    private RollbackManager() {
        log.info("RollbackManager initialized");
    }

    public static RollbackManager getInstance() {
        if (instance == null) {
            synchronized (RollbackManager.class) {
                if (instance == null) {
                    instance = new RollbackManager();
                }
            }
        }
        return instance;
    }

    /**
     * 注册一个检查点
     */
    public void registerCheckpoint(String checkpointName, Runnable rollbackAction) {
        registerCheckpoint(checkpointName, rollbackAction, RollbackPriority.NORMAL);
    }

    /**
     * 注册一个带优先级的检查点
     */
    public void registerCheckpoint(String checkpointName, Runnable rollbackAction, RollbackPriority priority) {
        Checkpoint checkpoint = new Checkpoint(checkpointName, rollbackAction, priority, System.currentTimeMillis());

        checkpoints.computeIfAbsent(checkpointName, k -> new LinkedList<>()).push(checkpoint);

        activeCheckpoints.get().push(checkpointName);

        log.info("Checkpoint registered: {} (priority: {})", checkpointName, priority);
        notifyListeners(new RollbackEvent(RollbackEventType.CHECKPOINT_REGISTERED, checkpointName, null));
    }

    /**
     * 标记检查点成功完成 - 清除该检查点的回滚动作
     */
    public void checkpointSuccess(String checkpointName) {
        Deque<Checkpoint> stack = checkpoints.get(checkpointName);
        if (stack != null && !stack.isEmpty()) {
            stack.pop();
            log.info("Checkpoint success: {} (remaining: {})", checkpointName, stack.size());
            notifyListeners(new RollbackEvent(RollbackEventType.CHECKPOINT_SUCCESS, checkpointName, null));
        }

        activeCheckpoints.get().remove(checkpointName);
    }

    /**
     * 回滚到指定检查点
     */
    public boolean rollbackTo(String checkpointName) {
        log.warn("Rollback triggered: {}", checkpointName);
        notifyListeners(new RollbackEvent(RollbackEventType.ROLLBACK_STARTED, checkpointName, null));

        Deque<Checkpoint> stack = checkpoints.get(checkpointName);
        if (stack == null || stack.isEmpty()) {
            log.error("Checkpoint not found or no actions to rollback: {}", checkpointName);
            return false;
        }

        List<String> rolledBack = new ArrayList<>();
        Exception firstError = null;

        for (Checkpoint cp : stack) {
            try {
                log.info("Executing rollback: {}", cp.name);
                cp.rollbackAction.run();
                rolledBack.add(cp.name);
            } catch (Exception e) {
                log.error("Rollback action failed: {}", cp.name, e);
                if (firstError == null) firstError = e;
            }
        }

        checkpoints.remove(checkpointName);

        if (firstError != null) {
            notifyListeners(new RollbackEvent(RollbackEventType.ROLLBACK_PARTIAL, checkpointName, firstError));
            log.error("Rollback partially failed, executed {} actions", rolledBack.size());
            return false;
        }

        notifyListeners(new RollbackEvent(RollbackEventType.ROLLBACK_COMPLETED, checkpointName, null));
        log.info("Rollback completed: {} actions executed", rolledBack.size());
        return true;
    }

    /**
     * 回滚所有检查点
     */
    public void rollbackAll() {
        log.warn("Full rollback triggered - all checkpoints");
        notifyListeners(new RollbackEvent(RollbackEventType.ROLLBACK_ALL_STARTED, null, null));

        List<String> checkpointNames = new ArrayList<>(checkpoints.keySet());
        for (String name : checkpointNames) {
            rollbackTo(name);
        }

        notifyListeners(new RollbackEvent(RollbackEventType.ROLLBACK_ALL_COMPLETED, null, null));
    }

    /**
     * 取消检查点
     */
    public void abandonCheckpoint(String checkpointName) {
        checkpoints.remove(checkpointName);
        activeCheckpoints.get().remove(checkpointName);
        log.info("Checkpoint abandoned: {}", checkpointName);
        notifyListeners(new RollbackEvent(RollbackEventType.CHECKPOINT_ABANDONED, checkpointName, null));
    }

    // ========== 状态快照管理 ==========

    public <T> void saveState(String stateName, T state) {
        stateSnapshots.put(stateName, new StateSnapshot(stateName, state, System.currentTimeMillis()));
        log.info("State saved: {}", stateName);
    }

    public <T> void saveState(String stateName, String version, T state) {
        stateSnapshots.put(stateName + ":" + version, new StateSnapshot(stateName + ":" + version, state, System.currentTimeMillis()));
        log.info("State saved: {} (version: {})", stateName, version);
    }

    @SuppressWarnings("unchecked")
    public <T> Optional<T> getState(String stateName) {
        StateSnapshot snapshot = stateSnapshots.get(stateName);
        return snapshot != null ? Optional.of((T) snapshot.state) : Optional.empty();
    }

    @SuppressWarnings("unchecked")
    public <T> Optional<T> getState(String stateName, String version) {
        StateSnapshot snapshot = stateSnapshots.get(stateName + ":" + version);
        return snapshot != null ? Optional.of((T) snapshot.state) : Optional.empty();
    }

    public void deleteState(String stateName) {
        stateSnapshots.remove(stateName);
        log.info("State deleted: {}", stateName);
    }

    public Set<String> listStates() {
        return new HashSet<>(stateSnapshots.keySet());
    }

    // ========== 监听器管理 ==========

    public void addListener(RollbackListener listener) {
        listeners.add(listener);
    }

    public void removeListener(RollbackListener listener) {
        listeners.remove(listener);
    }

    private void notifyListeners(RollbackEvent event) {
        for (RollbackListener listener : listeners) {
            try {
                listener.onRollbackEvent(event);
            } catch (Exception e) {
                log.error("Listener notification failed", e);
            }
        }
    }

    // ========== 内部类 ==========

    public static class Checkpoint {
        public final String name;
        public final Runnable rollbackAction;
        public final RollbackPriority priority;
        public final long timestamp;

        public Checkpoint(String name, Runnable rollbackAction, RollbackPriority priority, long timestamp) {
            this.name = name;
            this.rollbackAction = rollbackAction;
            this.priority = priority;
            this.timestamp = timestamp;
        }
    }

    public enum RollbackPriority {
        LOW(1), NORMAL(2), HIGH(3), CRITICAL(4);

        private final int level;
        RollbackPriority(int level) { this.level = level; }
        public int getLevel() { return level; }
    }

    public static class StateSnapshot {
        public final String name;
        public final Object state;
        public final long timestamp;

        public StateSnapshot(String name, Object state, long timestamp) {
            this.name = name;
            this.state = state;
            this.timestamp = timestamp;
        }
    }

    public enum RollbackEventType {
        CHECKPOINT_REGISTERED,
        CHECKPOINT_SUCCESS,
        CHECKPOINT_ABANDONED,
        ROLLBACK_STARTED,
        ROLLBACK_COMPLETED,
        ROLLBACK_PARTIAL,
        ROLLBACK_ALL_STARTED,
        ROLLBACK_ALL_COMPLETED
    }

    public static class RollbackEvent {
        public final RollbackEventType type;
        public final String checkpointName;
        public final Exception error;

        public RollbackEvent(RollbackEventType type, String checkpointName, Exception error) {
            this.type = type;
            this.checkpointName = checkpointName;
            this.error = error;
        }
    }

    public interface RollbackListener {
        void onRollbackEvent(RollbackEvent event);
    }

    /**
     * 执行带自动回滚的操作
     */
    public <T> T executeWithRollback(String checkpointName, Supplier<T> action, Runnable rollbackAction) {
        registerCheckpoint(checkpointName, rollbackAction);
        try {
            T result = action.get();
            checkpointSuccess(checkpointName);
            return result;
        } catch (Exception e) {
            rollbackTo(checkpointName);
            throw e;
        }
    }

    public CheckpointContext createContext(String checkpointName) {
        return new CheckpointContext(this, checkpointName);
    }

    public static class CheckpointContext implements AutoCloseable {
        private final RollbackManager manager;
        private final String checkpointName;
        private boolean success = false;

        CheckpointContext(RollbackManager manager, String checkpointName) {
            this.manager = manager;
            this.checkpointName = checkpointName;
        }

        public void markSuccess() { this.success = true; }

        @Override
        public void close() {
            if (success) {
                manager.checkpointSuccess(checkpointName);
            } else {
                manager.rollbackTo(checkpointName);
            }
        }
    }
}