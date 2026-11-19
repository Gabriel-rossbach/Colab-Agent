package com.colabfleet.model;

import com.colabfleet.security.SensitiveDataRedactor;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;

public final class Run {

    private static final int MAX_STORED_EVENTS = 10_000;

    private final String id;
    private final String request;
    private final boolean browserEnabled;
    private final Path runDir;
    private final Instant createdAt;
    private final Deque<ObjectNode> events = new ArrayDeque<>();

    private RunState state = RunState.PLANNING;
    private Plan plan;
    private RunResult result;
    private String error;
    private Instant updatedAt;
    private long sequence;

    public Run(String id, String request, boolean browserEnabled, Path runDir) {
        this.id = id;
        this.request = request;
        this.browserEnabled = browserEnabled;
        this.runDir = runDir;
        this.createdAt = Instant.now();
        this.updatedAt = createdAt;
    }

    public String getId() {
        return id;
    }

    public String getRequest() {
        return request;
    }

    public boolean isBrowserEnabled() {
        return browserEnabled;
    }

    public Path getRunDir() {
        return runDir;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public synchronized RunState getState() {
        return state;
    }

    public synchronized boolean hasPlan() {
        return plan != null;
    }

    public synchronized boolean hasResult() {
        return result != null;
    }

    public synchronized void changeState(RunState newState) {
        state = newState;
        updatedAt = Instant.now();
    }

    public synchronized void definePlan(Plan plan) {
        this.plan = plan;
        updatedAt = Instant.now();
    }

    public synchronized void defineResult(RunResult result) {
        this.result = result;
        updatedAt = Instant.now();
    }

    public synchronized void fail(String message) {
        state = RunState.FAILED;
        error = message;
        updatedAt = Instant.now();
    }

    public synchronized ObjectNode addEvent(ObjectNode event) {
        ObjectNode stored = event.deepCopy();
        stored.put("seq", ++sequence);
        if (!stored.has("timestamp") || stored.get("timestamp").isNull()) {
            stored.put("timestamp", Instant.now().toString());
        }
        if (events.size() == MAX_STORED_EVENTS) {
            events.removeFirst();
        }
        events.addLast(stored);
        return stored.deepCopy();
    }

    public synchronized List<ObjectNode> eventsAfter(long after, int limit) {
        return events.stream()
                .filter(event -> event.path("seq").asLong() > after)
                .limit(limit)
                .map(ObjectNode::deepCopy)
                .toList();
    }

    public synchronized RunResponse toResponse() {
        return new RunResponse(
                id,
                SensitiveDataRedactor.redact(request),
                browserEnabled,
                state,
                plan,
                state.isTerminal() ? result : null,
                SensitiveDataRedactor.redact(error),
                createdAt.toString(),
                updatedAt.toString());
    }
}
