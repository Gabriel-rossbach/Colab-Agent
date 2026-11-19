package com.colabfleet.process;

import com.colabfleet.config.FleetProperties;
import com.colabfleet.model.Run;
import com.colabfleet.security.SensitiveDataRedactor;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.annotation.PreDestroy;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

@Component
public class DefaultWorkerProcessManager implements WorkerProcessManager {

    static final long CANCEL_GRACE_MILLIS = 30_000;
    static final long DESTROY_GRACE_MILLIS = 2_000;
    private static final int MAX_STREAM_LINE_CHARS = 256_000;
    private static final Set<String> SUPPORTED_EVENTS = Set.of(
            "run.state", "machine.state", "task.state", "log", "plan.ready", "run.result");

    private static final Logger LOGGER = LoggerFactory.getLogger(DefaultWorkerProcessManager.class);

    private final FleetProperties properties;
    private final ObjectMapper objectMapper;
    private final Path repoRoot;
    private final Path workerPath;
    private final long cancelGraceMillis;
    private final long destroyGraceMillis;
    private ManagedProcess current;

    @Autowired
    public DefaultWorkerProcessManager(FleetProperties properties, ObjectMapper objectMapper) {
        this(properties, objectMapper, CANCEL_GRACE_MILLIS, DESTROY_GRACE_MILLIS);
    }

    DefaultWorkerProcessManager(
            FleetProperties properties,
            ObjectMapper objectMapper,
            long cancelGraceMillis,
            long destroyGraceMillis) {
        if (cancelGraceMillis < 0 || destroyGraceMillis < 0) {
            throw new IllegalArgumentException("As graças de cancelamento não podem ser negativas.");
        }
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.repoRoot = Path.of(properties.getRepoRoot()).toAbsolutePath().normalize();
        this.workerPath = repoRoot.resolve("fleet_worker.py");
        this.cancelGraceMillis = cancelGraceMillis;
        this.destroyGraceMillis = destroyGraceMillis;
    }

    @Override
    public void plan(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) throws IOException {
        start(run, WorkerCommand.PLAN, eventHandler, exitHandler);
    }

    @Override
    public void execute(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) throws IOException {
        start(run, WorkerCommand.EXECUTE, eventHandler, exitHandler);
    }

    private void start(
            Run run,
            WorkerCommand command,
            Consumer<ObjectNode> eventHandler,
            Consumer<ProcessExit> exitHandler) throws IOException {
        awaitPreviousPlan(run, command);

        synchronized (this) {
            if (current != null && current.process.isAlive()) {
                throw new WorkerBusyException();
            }

            List<String> arguments = new ArrayList<>();
            arguments.add(properties.getPythonBin());
            arguments.add(workerPath.toString());
            arguments.add(command.argument());
            arguments.add("--run-id");
            arguments.add(run.getId());
            if (command == WorkerCommand.PLAN) {
                arguments.add("--request");
                arguments.add(run.getRequest());
            }
            arguments.add("--run-dir");
            arguments.add(run.getRunDir().toString());
            if (run.isBrowserEnabled()) {
                arguments.add("--browser");
            }

            ProcessBuilder processBuilder = new ProcessBuilder(arguments);
            processBuilder.directory(repoRoot.toFile());
            processBuilder.redirectErrorStream(false);
            Process process = processBuilder.start();
            ManagedProcess managed = new ManagedProcess(run.getId(), command, process);
            current = managed;

            Thread stdoutThread = Thread.ofVirtual()
                    .name("fleet-stdout-" + run.getId())
                    .start(() -> readStream(process, true, eventHandler));
            Thread stderrThread = Thread.ofVirtual()
                    .name("fleet-stderr-" + run.getId())
                    .start(() -> readStream(process, false, eventHandler));
            Thread.ofVirtual()
                    .name("fleet-wait-" + run.getId())
                    .start(() -> awaitExit(managed, stdoutThread, stderrThread, exitHandler));
        }
    }

    private void awaitPreviousPlan(Run run, WorkerCommand command) {
        ManagedProcess previous;
        synchronized (this) {
            previous = current;
        }
        if (previous == null || !previous.process.isAlive()) {
            return;
        }
        if (command != WorkerCommand.EXECUTE
                || previous.command != WorkerCommand.PLAN
                || !previous.runId.equals(run.getId())) {
            throw new WorkerBusyException();
        }
        try {
            if (!previous.process.waitFor(3, TimeUnit.SECONDS)) {
                throw new WorkerBusyException();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new WorkerBusyException();
        }
    }

    private void readStream(Process process, boolean stdout, Consumer<ObjectNode> eventHandler) {
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                stdout ? process.getInputStream() : process.getErrorStream(), StandardCharsets.UTF_8))) {
            WorkerLine line;
            while ((line = readLine(reader)) != null) {
                if (line.oversized()) {
                    deliver(logEvent("Linha da saída do worker ignorada: limite de tamanho excedido."), eventHandler);
                } else if (stdout) {
                    deliverJsonLine(line.content(), eventHandler);
                } else {
                    deliver(logEvent(SensitiveDataRedactor.redact(line.content())), eventHandler);
                }
            }
        } catch (IOException exception) {
            if (process.isAlive()) {
                deliver(logEvent("Falha ao ler a saída do worker."), eventHandler);
            }
        }
    }

    private WorkerLine readLine(BufferedReader reader) throws IOException {
        StringBuilder line = new StringBuilder();
        boolean oversized = false;
        boolean readAny = false;
        int current;
        while ((current = reader.read()) != -1) {
            readAny = true;
            if (current == '\n') {
                break;
            }
            if (line.length() < MAX_STREAM_LINE_CHARS) {
                line.append((char) current);
            } else {
                oversized = true;
            }
        }
        if (!readAny) {
            return null;
        }
        if (!line.isEmpty() && line.charAt(line.length() - 1) == '\r') {
            line.deleteCharAt(line.length() - 1);
        }
        return new WorkerLine(line.toString(), oversized);
    }

    private void deliverJsonLine(String line, Consumer<ObjectNode> eventHandler) {
        try {
            JsonNode parsed = objectMapper.readTree(line);
            if (parsed instanceof ObjectNode event) {
                if (!SUPPORTED_EVENTS.contains(event.path("type").asText(""))) {
                    deliver(logEvent("Evento de stdout ignorado: tipo não suportado."), eventHandler);
                    return;
                }
                deliver(SensitiveDataRedactor.redactJson(event), eventHandler);
            } else {
                deliver(logEvent("Linha de stdout ignorada: o evento JSON deve ser um objeto."), eventHandler);
            }
        } catch (IOException exception) {
            deliver(logEvent("Linha de stdout ignorada: JSON inválido."), eventHandler);
        }
    }

    private void deliver(ObjectNode event, Consumer<ObjectNode> eventHandler) {
        try {
            eventHandler.accept(event);
        } catch (RuntimeException exception) {
            LOGGER.warn("Falha ao processar um evento do worker.");
        }
    }

    private ObjectNode logEvent(String message) {
        ObjectNode event = objectMapper.createObjectNode();
        event.put("type", "log");
        event.put("message", message);
        return event;
    }

    private void awaitExit(
            ManagedProcess managed,
            Thread stdoutThread,
            Thread stderrThread,
            Consumer<ProcessExit> exitHandler) {
        int exitCode;
        try {
            exitCode = managed.process.waitFor();
            awaitReader(stdoutThread, managed.process.getInputStream());
            awaitReader(stderrThread, managed.process.getErrorStream());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            managed.process.destroyForcibly();
            closeQuietly(managed.process.getInputStream());
            closeQuietly(managed.process.getErrorStream());
            exitCode = 137;
        }

        synchronized (this) {
            if (current == managed) {
                current = null;
            }
        }
        try {
            exitHandler.accept(new ProcessExit(managed.runId, managed.command, exitCode));
        } catch (RuntimeException exception) {
            LOGGER.warn("Falha ao concluir o subprocesso do worker.");
        }
    }

    private void awaitReader(Thread readerThread, InputStream stream) throws InterruptedException {
        readerThread.join(destroyGraceMillis);
        if (readerThread.isAlive()) {
            closeQuietly(stream);
            readerThread.join(destroyGraceMillis);
        }
    }

    private void closeQuietly(InputStream stream) {
        try {
            stream.close();
        } catch (IOException exception) {
            LOGGER.debug("Falha ao fechar a saída do worker.");
        }
    }

    @Override
    public boolean cancel(String runId) {
        ManagedProcess managed;
        synchronized (this) {
            managed = current;
            if (managed == null || !managed.runId.equals(runId) || !managed.process.isAlive()) {
                return false;
            }
            if (!managed.cancellationScheduled.compareAndSet(false, true)) {
                return true;
            }
        }

        Thread.ofVirtual().name("fleet-cancel-" + runId).start(() -> {
            try {
                Thread.sleep(cancelGraceMillis);
                if (managed.process.isAlive()) {
                    managed.process.destroy();
                }
                Thread.sleep(destroyGraceMillis);
                if (managed.process.isAlive()) {
                    managed.process.destroyForcibly();
                }
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
            }
        });
        return true;
    }

    @PreDestroy
    public void shutdown() {
        ManagedProcess managed;
        synchronized (this) {
            managed = current;
            current = null;
        }
        if (managed == null) {
            return;
        }
        managed.process.destroy();
        try {
            if (!managed.process.waitFor(500, TimeUnit.MILLISECONDS)) {
                managed.process.destroyForcibly();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            managed.process.destroyForcibly();
        }
    }

    private record WorkerLine(String content, boolean oversized) {
    }

    private static final class ManagedProcess {
        private final String runId;
        private final WorkerCommand command;
        private final Process process;
        private final AtomicBoolean cancellationScheduled = new AtomicBoolean();

        private ManagedProcess(String runId, WorkerCommand command, Process process) {
            this.runId = runId;
            this.command = command;
            this.process = process;
        }
    }
}
