package com.colabfleet.model;

public enum RunState {
    PLANNING,
    WAITING_CONFIRMATION,
    EXECUTING,
    CANCELLING,
    COMPLETED,
    FAILED,
    CANCELLED;

    public boolean isTerminal() {
        return this == COMPLETED || this == FAILED || this == CANCELLED;
    }

    public boolean isActive() {
        return !isTerminal();
    }
}
