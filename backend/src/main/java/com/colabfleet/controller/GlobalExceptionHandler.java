package com.colabfleet.controller;

import com.colabfleet.exception.ArtifactAccessException;
import com.colabfleet.exception.RunConflictException;
import com.colabfleet.exception.RunInfrastructureException;
import com.colabfleet.exception.RunNotFoundException;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger LOGGER = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(RunNotFoundException.class)
    public ResponseEntity<Map<String, String>> notFound(RunNotFoundException exception) {
        return error(HttpStatus.NOT_FOUND, exception.getMessage());
    }

    @ExceptionHandler(RunConflictException.class)
    public ResponseEntity<Map<String, String>> conflict(RunConflictException exception) {
        return error(HttpStatus.CONFLICT, exception.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> validation(MethodArgumentNotValidException exception) {
        String message = exception.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(fieldError -> fieldError.getDefaultMessage() == null
                        ? "Dados da solicitação inválidos."
                        : fieldError.getDefaultMessage())
                .orElse("Dados da solicitação inválidos.");
        return error(HttpStatus.BAD_REQUEST, message);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class})
    public ResponseEntity<Map<String, String>> malformedRequest(Exception exception) {
        return error(HttpStatus.BAD_REQUEST, "Solicitação JSON ou parâmetro inválido.");
    }

    @ExceptionHandler({RunInfrastructureException.class, ArtifactAccessException.class})
    public ResponseEntity<Map<String, String>> infrastructure(RuntimeException exception) {
        LOGGER.error("Falha de infraestrutura na API.", exception);
        return error(HttpStatus.INTERNAL_SERVER_ERROR, exception.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, String>> internal(Exception exception) {
        LOGGER.error("Erro interno na API.", exception);
        return error(HttpStatus.INTERNAL_SERVER_ERROR, "Erro interno do servidor.");
    }

    private ResponseEntity<Map<String, String>> error(HttpStatus status, String message) {
        return ResponseEntity.status(status).body(Map.of("error", message));
    }
}
