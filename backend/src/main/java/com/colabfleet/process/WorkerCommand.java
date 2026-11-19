package com.colabfleet.process;

public enum WorkerCommand {
    PLAN("plan"),
    EXECUTE("execute");

    private final String argument;

    WorkerCommand(String argument) {
        this.argument = argument;
    }

    public String argument() {
        return argument;
    }
}
