package com.colabfleet.exception;

public class ArtifactAccessException extends RuntimeException {

    public ArtifactAccessException(Throwable cause) {
        super("Não foi possível ler os artefatos da execução.", cause);
    }
}
