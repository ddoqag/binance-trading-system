package com.trading.domain.trading.state;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;

/**
 * Order State Machine - manages order lifecycle transitions.
 */
public class OrderStateMachine {

    private OrderState currentState;
    private final String orderId;
    private long stateChangeTime;

    public OrderStateMachine(String orderId) {
        this.orderId = orderId;
        this.currentState = OrderState.PENDING;
        this.stateChangeTime = System.currentTimeMillis();
    }

    public OrderStateMachine(String orderId, OrderState initialState) {
        this.orderId = orderId;
        this.currentState = initialState;
        this.stateChangeTime = System.currentTimeMillis();
    }

    /**
     * Transition based on execution report.
     */
    public void onExecutionReport(ExecutionReport report) {
        OrderStatus status = report.getStatus();
        if (status == OrderStatus.FILLED) {
            transitionTo(OrderState.FILLED);
        } else if (status == OrderStatus.PARTIALLY_FILLED) {
            transitionTo(OrderState.PARTIALLY_FILLED);
        } else if (status == OrderStatus.CANCELLED) {
            transitionTo(OrderState.CANCELLED);
        } else if (status == OrderStatus.REJECTED) {
            transitionTo(OrderState.REJECTED);
        } else if (status == OrderStatus.NEW || status == OrderStatus.SENT) {
            transitionTo(OrderState.ACCEPTED);
        }
    }

    /**
     * Manual cancel request.
     */
    public boolean cancel() {
        if (currentState.isTerminal()) {
            return false;
        }
        transitionTo(OrderState.CANCELLED);
        return true;
    }

    /**
     * Transition to new state (validates transition).
     */
    public void transitionTo(OrderState newState) {
        currentState = currentState.transition(newState);
        stateChangeTime = System.currentTimeMillis();
    }

    public OrderState getCurrentState() {
        return currentState;
    }

    public String getOrderId() {
        return orderId;
    }

    public long getStateChangeTime() {
        return stateChangeTime;
    }

    public long getTimeInCurrentState() {
        return System.currentTimeMillis() - stateChangeTime;
    }

    public boolean isTerminal() {
        return currentState.isTerminal();
    }

    @Override
    public String toString() {
        return "OrderStateMachine{orderId=" + orderId + ", state=" + currentState + ", timeInState=" + getTimeInCurrentState() + "ms}";
    }
}