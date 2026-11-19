package com.colabfleet.exception;

public class RunNotFoundException extends RuntimeException {

    public RunNotFoundException() {
        super("Execução não encontrada.");
    }
}
