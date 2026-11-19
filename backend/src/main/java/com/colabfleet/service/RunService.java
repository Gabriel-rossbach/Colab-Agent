package com.colabfleet.service;

import com.colabfleet.config.FleetProperties;
import com.colabfleet.exception.ArtifactAccessException;
import com.colabfleet.exception.RunConflictException;
import com.colabfleet.exception.RunInfrastructureException;
import com.colabfleet.exception.RunNotFoundException;
import com.colabfleet.model.ArtifactsResponse;
import com.colabfleet.model.Plan;
import com.colabfleet.model.PlanTask;
import com.colabfleet.model.Run;
import com.colabfleet.model.RunResponse;
import com.colabfleet.model.RunResult;
import com.colabfleet.model.RunState;
import com.colabfleet.process.ProcessExit;
import com.colabfleet.process.WorkerBusyException;
import com.colabfleet.process.WorkerCommand;
import com.colabfleet.process.WorkerProcessManager;
import com.colabfleet.security.SensitiveDataRedactor;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;

@Service
public class RunService {

    private static final int EVENT_LIMIT = 500;
    private static final int MAX_PLAN_TASKS = 256;
    private static final int MAX_SUMMARY_BYTES = 1_000_000;
    private static final int MAX_RESULTS_BYTES = 5_000_000;
    private static final Set<String> SUPPORTED_EVENTS = Set.of(
            "run.state", "machine.state", "task.state", "log", "plan.ready", "run.result");

    private final FleetProperties properties;
    private final ObjectMapper objectMapper;
    private final WorkerProcessManager processManager;
    private final Map<String, Run> runs = new ConcurrentHashMap<>();
    private final Map<String, WorkerCommand> activeCommands = new ConcurrentHashMap<>();
    private final Object lifecycleLock = new Object();

    public RunService(FleetProperties properties, ObjectMapper objectMapper, WorkerProcessManager processManager) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.processManager = processManager;
    }

    public RunResponse create(String request, boolean browserEnabled) {
        synchronized (lifecycleLock) {
            boolean hasActiveRun = runs.values().stream().anyMatch(run -> run.getState().isActive());
            if (hasActiveRun) {
                throw new RunConflictException("Já existe uma execução ativa; aguarde ou cancele antes de criar outra.");
            }

            String id = UUID.randomUUID().toString();
            Path runDir = properties.getRunsDir().toAbsolutePath().normalize().resolve(id);
            try {
                Files.createDirectories(runDir);
            } catch (IOException exception) {
                throw new RunInfrastructureException("Não foi possível preparar o diretório da execução.", exception);
            }

            Run run = new Run(id, request, browserEnabled, runDir);
            runs.put(id, run);
            activeCommands.put(id, WorkerCommand.PLAN);
            try {
                processManager.plan(run,
                        event -> receiveEvent(id, WorkerCommand.PLAN, event),
                        this::processFinished);
            } catch (WorkerBusyException exception) {
                activeCommands.remove(id);
                runs.remove(id);
                throw new RunConflictException(exception.getMessage());
            } catch (IOException | RuntimeException exception) {
                failToStart(run, "Não foi possível iniciar o planejamento.");
            }
            return run.toResponse();
        }
    }

    public List<RunResponse> list() {
        return runs.values().stream()
                .sorted(Comparator.comparing(Run::getCreatedAt).reversed())
                .map(Run::toResponse)
                .toList();
    }

    public RunResponse find(String id) {
        return requiredRun(id).toResponse();
    }

    public RunResponse confirm(String id) {
        synchronized (lifecycleLock) {
            Run run = requiredRun(id);
            if (run.getState() != RunState.WAITING_CONFIRMATION) {
                throw new RunConflictException("A execução só pode ser confirmada quando estiver aguardando confirmação.");
            }
            run.changeState(RunState.EXECUTING);
            activeCommands.put(id, WorkerCommand.EXECUTE);
            try {
                processManager.execute(run,
                        event -> receiveEvent(id, WorkerCommand.EXECUTE, event),
                        this::processFinished);
            } catch (WorkerBusyException exception) {
                activeCommands.put(id, WorkerCommand.PLAN);
                run.changeState(RunState.WAITING_CONFIRMATION);
                throw new RunConflictException(exception.getMessage());
            } catch (IOException | RuntimeException exception) {
                failToStart(run, "Não foi possível iniciar a execução.");
            }
            return run.toResponse();
        }
    }

    public RunResponse cancel(String id) {
        synchronized (lifecycleLock) {
            Run run = requiredRun(id);
            RunState state = run.getState();
            if (state == RunState.CANCELLED) {
                return run.toResponse();
            }
            if (state.isTerminal()) {
                throw new RunConflictException("Uma execução concluída ou falha não pode ser cancelada.");
            }

            try {
                Files.writeString(
                        run.getRunDir().resolve("cancel.requested"),
                        "",
                        StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE_NEW,
                        StandardOpenOption.WRITE);
            } catch (FileAlreadyExistsException exception) {
                // O marcador já criado torna novas solicitações de cancelamento idempotentes.
            } catch (IOException exception) {
                throw new RunInfrastructureException("Não foi possível solicitar o cancelamento.", exception);
            }

            if (state != RunState.CANCELLING) {
                run.changeState(RunState.CANCELLING);
                addBackendLog(run, "Cancelamento solicitado.");
            }
            boolean processActive = processManager.cancel(id);
            if (!processActive) {
                activeCommands.remove(id);
                run.changeState(RunState.CANCELLED);
            }
            return run.toResponse();
        }
    }

    public List<ObjectNode> events(String id, long after) {
        Run run = requiredRun(id);
        return run.eventsAfter(Math.max(0, after), EVENT_LIMIT);
    }

    public ArtifactsResponse artifacts(String id) {
        Run run = requiredRun(id);
        String summary = SensitiveDataRedactor.redact(readSummary(run.getRunDir().resolve("summary.md")));
        ArrayNode results = SensitiveDataRedactor.redactJson(readResults(run.getRunDir().resolve("results.json")));
        return new ArtifactsResponse(summary, results);
    }

    private Run requiredRun(String id) {
        Run run = runs.get(id);
        if (run == null) {
            throw new RunNotFoundException();
        }
        return run;
    }

    private void receiveEvent(String id, WorkerCommand source, ObjectNode event) {
        synchronized (lifecycleLock) {
            Run run = runs.get(id);
            if (run == null || event == null || activeCommands.get(id) != source) {
                return;
            }
            String type = event.path("type").asText("");
            if (!SUPPORTED_EVENTS.contains(type)) {
                return;
            }
            ObjectNode safeEvent = SensitiveDataRedactor.redactJson(event);
            run.addEvent(safeEvent);
            try {
                switch (type) {
                    case "run.state" -> updateRunState(run, safeEvent);
                    case "plan.ready" -> updatePlan(run, safeEvent.get("plan"));
                    case "run.result" -> updateResult(run, safeEvent.get("result"));
                    default -> {
                        // Logs e estados de máquinas/tarefas já ficam disponíveis no polling.
                    }
                }
            } catch (JsonProcessingException | RuntimeException exception) {
                if (run.getState() != RunState.CANCELLING) {
                    run.fail("O worker enviou um evento inválido.");
                    addBackendLog(run, "Evento do worker inválido; a execução foi marcada como falha.");
                }
            }
        }
    }

    private void updateRunState(Run run, ObjectNode event) {
        RunState current = run.getState();
        if (current.isTerminal()) {
            return;
        }
        RunState incoming = RunState.valueOf(event.path("state").asText());
        if (current == RunState.CANCELLING) {
            if (incoming == RunState.CANCELLED) {
                run.changeState(RunState.CANCELLED);
            }
            return;
        }
        if (!isAllowedTransition(current, incoming)) {
            throw new IllegalArgumentException("Transição de estado inválida");
        }
        if (incoming == RunState.WAITING_CONFIRMATION && !run.hasPlan()) {
            throw new IllegalArgumentException("Confirmação sem plano");
        }
        if (incoming == RunState.COMPLETED && !run.hasResult()) {
            throw new IllegalArgumentException("Conclusão sem resultado");
        }
        if (incoming == RunState.FAILED) {
            String message = event.path("message").asText("").trim();
            run.fail(message.isEmpty() ? "A execução falhou." : message);
        } else {
            run.changeState(incoming);
        }
    }

    private boolean isAllowedTransition(RunState current, RunState incoming) {
        if (current == incoming) {
            return true;
        }
        return switch (current) {
            case PLANNING -> incoming == RunState.WAITING_CONFIRMATION
                    || incoming == RunState.FAILED
                    || incoming == RunState.CANCELLING
                    || incoming == RunState.CANCELLED;
            case WAITING_CONFIRMATION -> incoming == RunState.FAILED
                    || incoming == RunState.CANCELLING
                    || incoming == RunState.CANCELLED;
            case EXECUTING -> incoming == RunState.COMPLETED
                    || incoming == RunState.FAILED
                    || incoming == RunState.CANCELLING
                    || incoming == RunState.CANCELLED;
            case CANCELLING, COMPLETED, FAILED, CANCELLED -> false;
        };
    }

    private void updatePlan(Run run, JsonNode planNode) throws JsonProcessingException {
        if (run.getState() != RunState.PLANNING) {
            return;
        }
        if (planNode == null || !planNode.isObject()) {
            throw new IllegalArgumentException("Plano ausente");
        }
        Plan plan = objectMapper.treeToValue(planNode, Plan.class);
        if (plan.request() == null || plan.tasks().isEmpty() || plan.tasks().size() > MAX_PLAN_TASKS) {
            throw new IllegalArgumentException("Plano incompleto");
        }
        for (PlanTask task : plan.tasks()) {
            if (task == null || task.cpu() == null || task.task() == null || task.prompt() == null) {
                throw new IllegalArgumentException("Tarefa do plano incompleta");
            }
        }
        run.definePlan(plan);
    }

    private void updateResult(Run run, JsonNode resultNode) throws JsonProcessingException {
        if (run.getState() != RunState.EXECUTING) {
            return;
        }
        if (resultNode == null || !resultNode.isObject()) {
            throw new IllegalArgumentException("Resultado ausente");
        }
        RunResult result = objectMapper.treeToValue(resultNode, RunResult.class);
        if (result.totalTasks() < 0
                || result.completedTasks() < 0
                || result.completedTasks() > result.totalTasks()
                || result.successful() < 0
                || result.successful() > result.completedTasks()) {
            throw new IllegalArgumentException("Resultado inconsistente");
        }
        run.defineResult(result);
    }

    private void processFinished(ProcessExit exit) {
        synchronized (lifecycleLock) {
            activeCommands.remove(exit.runId(), exit.command());
            Run run = runs.get(exit.runId());
            if (run == null || run.getState().isTerminal()) {
                return;
            }
            RunState state = run.getState();
            if (state == RunState.CANCELLING) {
                run.changeState(RunState.CANCELLED);
                return;
            }
            if (exit.command() == WorkerCommand.PLAN && state == RunState.EXECUTING) {
                return;
            }
            if (exit.exitCode() != 0) {
                run.fail("O worker terminou com código " + exit.exitCode() + ".");
                return;
            }
            if (exit.command() == WorkerCommand.PLAN) {
                if (state == RunState.PLANNING) {
                    run.fail("O planejamento terminou sem aguardar confirmação.");
                }
                return;
            }
            if (state == RunState.EXECUTING) {
                if (run.hasResult()) {
                    run.changeState(RunState.COMPLETED);
                } else {
                    run.fail("O worker terminou sem informar o resultado da execução.");
                }
            }
        }
    }

    private void failToStart(Run run, String message) {
        activeCommands.remove(run.getId());
        run.fail(message);
        addBackendLog(run, message);
    }

    private void addBackendLog(Run run, String message) {
        ObjectNode event = objectMapper.createObjectNode();
        event.put("type", "log");
        event.put("message", message);
        run.addEvent(event);
    }

    private String readSummary(Path path) {
        try {
            String content = readArtifact(path, MAX_SUMMARY_BYTES);
            return content == null ? "" : content;
        } catch (IOException | RuntimeException exception) {
            throw new ArtifactAccessException(exception);
        }
    }

    private ArrayNode readResults(Path path) {
        ArrayNode empty = objectMapper.createArrayNode();
        try {
            String content = readArtifact(path, MAX_RESULTS_BYTES);
            if (content == null) {
                return empty;
            }
            JsonNode root = objectMapper.readTree(content);
            if (root != null && root.isArray()) {
                return (ArrayNode) root;
            }
            if (root != null && root.path("results").isArray()) {
                return (ArrayNode) root.path("results");
            }
            return empty;
        } catch (IOException | RuntimeException exception) {
            throw new ArtifactAccessException(exception);
        }
    }

    private String readArtifact(Path path, int maximumBytes) throws IOException {
        if (Files.notExists(path, LinkOption.NOFOLLOW_LINKS)) {
            return null;
        }
        try (InputStream input = Files.newInputStream(
                path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] content = input.readNBytes(maximumBytes + 1);
            if (content.length > maximumBytes) {
                throw new IOException("O artefato excede o tamanho máximo permitido.");
            }
            return new String(content, StandardCharsets.UTF_8);
        }
    }
}
