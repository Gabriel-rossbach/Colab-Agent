package com.colabfleet.model;

public record RunResponse(
        String id,
        String request,
        boolean browserEnabled,
        RunState state,
        Plan plan,
        RunResult result,
        String error,
        String createdAt,
        String updatedAt) {
}
