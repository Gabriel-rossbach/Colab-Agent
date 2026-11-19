package com.colabfleet.model;

import java.util.List;

public record Plan(String request, List<PlanTask> tasks) {

    public Plan {
        tasks = tasks == null ? List.of() : List.copyOf(tasks);
    }
}
