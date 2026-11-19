package com.colabfleet.model;

public record RunResult(int totalTasks, int completedTasks, int successful, Boolean gatePass) {
}
