package com.colabfleet.process;

public record ProcessExit(String runId, WorkerCommand command, int exitCode) {
}
