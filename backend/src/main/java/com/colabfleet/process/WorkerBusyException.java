package com.colabfleet.process;

public class WorkerBusyException extends RuntimeException {

    public WorkerBusyException() {
        super("Já existe um subprocesso da fleet ativo.");
    }
}
