package com.trading.messaging;

/** Events related to position changes. */
public sealed interface PositionEvent extends DomainEvent permits
        PositionOpenedEvent, PositionModifiedEvent, PositionClosedEvent {}
