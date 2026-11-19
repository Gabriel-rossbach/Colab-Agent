package com.colabfleet.controller;

import com.colabfleet.model.ArtifactsResponse;
import com.colabfleet.model.CreateRunRequest;
import com.colabfleet.model.RunResponse;
import com.colabfleet.service.RunService;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class FleetController {

    private final RunService runService;

    public FleetController(RunService runService) {
        this.runService = runService;
    }

    @GetMapping("/health")
    public Map<String, String> health() {
        return Map.of("status", "UP");
    }

    @PostMapping("/runs")
    public ResponseEntity<RunResponse> create(@Valid @RequestBody CreateRunRequest request) {
        RunResponse response = runService.create(request.request(), request.browserEnabled());
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(response);
    }

    @GetMapping("/runs")
    public List<RunResponse> list() {
        return runService.list();
    }

    @GetMapping("/runs/{id}")
    public RunResponse find(@PathVariable String id) {
        return runService.find(id);
    }

    @PostMapping("/runs/{id}/confirm")
    public RunResponse confirm(@PathVariable String id) {
        return runService.confirm(id);
    }

    @PostMapping("/runs/{id}/cancel")
    public RunResponse cancel(@PathVariable String id) {
        return runService.cancel(id);
    }

    @GetMapping("/runs/{id}/events")
    public List<ObjectNode> events(@PathVariable String id, @RequestParam(defaultValue = "0") long after) {
        return runService.events(id, after);
    }

    @GetMapping("/runs/{id}/artifacts")
    public ArtifactsResponse artifacts(@PathVariable String id) {
        return runService.artifacts(id);
    }
}
