package com.trading.actors;

import com.trading.domain.trading.model.*;
import com.trading.messaging.*;
import com.trading.messaging.messages.*;
import com.trading.adapter.execution.BinanceExchangeAdapter;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Execution Actor - handles order lifecycle management.
 * Receives order commands and publishes order events.
 */
public class ExecutionActor extends Actor {

    private final BinanceExchangeAdapter adapter;
    private final Map<String, OrderContext> activeOrders = new ConcurrentHashMap<>();
    private final AtomicLong totalOrders = new AtomicLong(0);

    public ExecutionActor(BinanceExchangeAdapter adapter) {
        super("ExecutionActor");
        this.adapter = adapter;
    }

    @Override
    public void receive(Command command) {
        if (command instanceof SubmitOrderCommand) {
            handleSubmit((SubmitOrderCommand) command);
        } else if (command instanceof CancelOrderCommand) {
            handleCancel((CancelOrderCommand) command);
        } else if (command instanceof ModifyOrderCommand) {
            handleModify((ModifyOrderCommand) command);
        }
    }

    @Override
    public void receive(DomainEvent event) {
        // Handle events from other actors if needed
    }

    private void handleSubmit(SubmitOrderCommand cmd) {
        totalOrders.incrementAndGet();

        // Create order object with correct constructor
        Order order = new Order(
            cmd.orderId(),
            cmd.symbol(),
            cmd.side(),
            cmd.orderType(),
            cmd.quantity(),
            cmd.price(),
            "ExecutionActor",  // strategy
            0.5               // urgency
        );

        // Store context
        activeOrders.put(cmd.orderId(), new OrderContext(cmd, order));

        // Send to exchange
        ExecutionReport report = adapter.sendOrder(order);

        // Publish event based on result
        if (report.getStatus() == OrderStatus.FILLED) {
            publish(new OrderFilledEvent(
                cmd.orderId(),
                cmd.symbol(),
                cmd.side(),
                cmd.orderType(),
                cmd.quantity(),
                cmd.price(),
                report.getFilledQuantity(),
                report.getAvgFillPrice(),
                0.0 // PnL calculated by RiskManager
            ));
        } else if (report.getStatus() == OrderStatus.REJECTED) {
            publish(new OrderRejectedEvent(
                cmd.orderId(),
                cmd.symbol(),
                cmd.side(),
                cmd.orderType(),
                cmd.quantity(),
                cmd.price(),
                "Order rejected by exchange"
            ));
        } else {
            // Order accepted but not yet filled
            publish(new OrderAcceptedEvent(
                cmd.orderId(),
                cmd.symbol(),
                cmd.side(),
                cmd.orderType(),
                cmd.quantity(),
                cmd.price(),
                System.currentTimeMillis()
            ));
        }
    }

    private void handleCancel(CancelOrderCommand cmd) {
        boolean success = adapter.cancelOrder(cmd.orderId(), cmd.binanceOrderId());

        if (success) {
            activeOrders.remove(cmd.orderId());
            publish(new OrderCancelledEvent(
                cmd.orderId(),
                cmd.symbol(),
                null, // side not tracked for cancels
                null, // type not tracked for cancels
                0,    // quantity not tracked for cancels
                0     // filled qty not tracked for cancels
            ));
        }
    }

    private void handleModify(ModifyOrderCommand cmd) {
        // Cancel original order
        CancelOrderCommand cancelCmd = new CancelOrderCommand(cmd.orderId(), cmd.binanceOrderId(), cmd.symbol(), null);
        handleCancel(cancelCmd);

        // Note: Full modify would need original order details from context
        // For now, just cancel - resubmit with new params would be done at strategy level
    }

    // Order context for tracking
    private static class OrderContext {
        final SubmitOrderCommand command;
        final Order order;

        OrderContext(SubmitOrderCommand command, Order order) {
            this.command = command;
            this.order = order;
        }
    }
}
