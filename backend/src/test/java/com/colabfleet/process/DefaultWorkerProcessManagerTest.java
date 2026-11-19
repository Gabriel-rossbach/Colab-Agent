package com.colabfleet.process;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.colabfleet.config.FleetProperties;
import com.colabfleet.model.Run;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Queue;
import java.util.UUID;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DefaultWorkerProcessManagerTest {

    @TempDir
    Path tempDir;

    private FleetProperties properties;
    private ObjectMapper objectMapper;
    private DefaultWorkerProcessManager processManager;
    private Queue<ObjectNode> events;
    private Queue<ProcessExit> exits;

    @BeforeEach
    void setUp() {
        properties = new FleetProperties();
        properties.setRepoRoot(tempDir.toString());
        properties.setPythonBin("/bin/sh");
        objectMapper = new ObjectMapper();
        processManager = new DefaultWorkerProcessManager(properties, objectMapper, 50, 20);
        events = new ConcurrentLinkedQueue<>();
        exits = new ConcurrentLinkedQueue<>();
    }

    @AfterEach
    void tearDown() {
        processManager.shutdown();
    }

    @Test
    void buildsPlanAndExecuteCommandsAndRedactsBothStreams() throws Exception {
        writeWorker("""
                printf '%s\\n' "$@" > "args-$1.txt"
                printf '%s\\n' '{"type":"log","message":"stdout NVIDIA_API_KEY=segredo-do-worker"}'
                printf '%s\\n' '{"type":"log","message":"campo","NVIDIA_API_KEY":"segredo-do-worker"}'
                printf '%s\\n' 'stderr NVIDIA_API_KEY="segredo do worker"' >&2
                """);
        String runId = UUID.randomUUID().toString();
        String request = "pesquisar carros; $(touch should-not-exist)";
        Path runDir = Files.createDirectories(tempDir.resolve("run"));
        Run run = new Run(runId, request, true, runDir);

        CountDownLatch planExit = new CountDownLatch(1);
        processManager.plan(run, events::add, exit -> recordExit(exit, planExit));
        assertTrue(planExit.await(5, TimeUnit.SECONDS));

        CountDownLatch executeExit = new CountDownLatch(1);
        processManager.execute(run, events::add, exit -> recordExit(exit, executeExit));
        assertTrue(executeExit.await(5, TimeUnit.SECONDS));

        assertEquals(List.of(
                "plan", "--run-id", runId, "--request", request,
                "--run-dir", runDir.toString(), "--browser"),
                Files.readAllLines(tempDir.resolve("args-plan.txt")));
        assertEquals(List.of(
                "execute", "--run-id", runId,
                "--run-dir", runDir.toString(), "--browser"),
                Files.readAllLines(tempDir.resolve("args-execute.txt")));
        assertEquals(2, exits.size());
        assertFalse(Files.exists(tempDir.resolve("should-not-exist")));
        assertEquals(6, events.size());
        for (ObjectNode event : events) {
            String serialized = event.toString();
            assertFalse(serialized.contains("segredo-do-worker"));
            assertFalse(serialized.contains("segredo do worker"));
        }
        assertTrue(events.stream().anyMatch(event -> event.toString().contains("[OCULTO]")));
    }

    @Test
    void rejectsMalformedUnknownAndOversizedWorkerOutput() throws Exception {
        writeWorker("""
                printf '%s\\n' 'not-json NVIDIA_API_KEY=segredo-do-worker'
                printf '%s\\n' '[1,2]'
                printf '%s\\n' '{"type":"unexpected","message":"nao propagar"}'
                head -c 256001 /dev/zero | tr '\\000' 'x'
                printf '\\n'
                printf '%s\\n' '{"type":"log","message":"evento-final"}'
                """);
        Run run = run("safe-request");
        CountDownLatch exited = new CountDownLatch(1);

        processManager.plan(run, events::add, exit -> recordExit(exit, exited));

        assertTrue(exited.await(5, TimeUnit.SECONDS));
        assertEquals(5, events.size());
        String serialized = events.toString();
        assertFalse(serialized.contains("segredo-do-worker"));
        assertFalse(serialized.contains("nao propagar"));
        assertFalse(serialized.contains("xxx"));
        assertTrue(serialized.contains("JSON inválido"));
        assertTrue(serialized.contains("deve ser um objeto"));
        assertTrue(serialized.contains("tipo não suportado"));
        assertTrue(serialized.contains("limite de tamanho excedido"));
        assertTrue(serialized.contains("evento-final"));
    }

    @Test
    void rejectsConcurrentProcessesAndShutdownTerminatesTheActiveWorker() throws Exception {
        writeWorker("""
                printf '%s\\n' "$1" > "started-$1.txt"
                while :; do :; done
                """);
        Run first = run("first-request");
        Run second = run("second-request");
        CountDownLatch exited = new CountDownLatch(1);
        processManager.plan(first, events::add, exit -> recordExit(exit, exited));
        awaitFile(tempDir.resolve("started-plan.txt"));

        assertThrows(WorkerBusyException.class,
                () -> processManager.plan(second, events::add, exit -> { }));
        assertTrue(processManager.cancel(first.getId()));
        assertTrue(processManager.cancel(first.getId()));

        processManager.shutdown();

        assertTrue(exited.await(5, TimeUnit.SECONDS));
        assertFalse(processManager.cancel(first.getId()));
    }

    @Test
    void cancelUsesThirtySecondDefaultAndShortConfigurableFallback() throws Exception {
        assertTrue(DefaultWorkerProcessManager.CANCEL_GRACE_MILLIS >= 30_000);
        writeWorker("""
                trap '' TERM
                printf '%s\\n' "$1" > "started-$1.txt"
                while :; do :; done
                """);
        processManager.shutdown();
        processManager = new DefaultWorkerProcessManager(properties, objectMapper, 100, 50);
        Run run = run("safe-request");
        CountDownLatch exited = new CountDownLatch(1);
        processManager.plan(run, events::add, exit -> recordExit(exit, exited));
        awaitFile(tempDir.resolve("started-plan.txt"));

        long cancellationStarted = System.nanoTime();
        assertTrue(processManager.cancel(run.getId()));

        assertTrue(exited.await(2, TimeUnit.SECONDS));
        long elapsedMillis = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - cancellationStarted);
        assertTrue(elapsedMillis >= 100, "O fallback não aguardou a graça cooperativa configurada.");
        assertEquals(1, exits.size());
    }

    @Test
    void executeWaitsForThePreviousPlanOfTheSameRun() throws Exception {
        writeWorker("""
                if [ "$1" = "plan" ]; then
                    printf '%s\\n' '{"type":"run.state","state":"WAITING_CONFIRMATION"}'
                    sleep 1
                else
                    printf '%s\\n' '{"type":"log","message":"execute-started"}'
                fi
                """);
        Run run = run("safe-request");
        CountDownLatch exited = new CountDownLatch(2);

        processManager.plan(run, events::add, exit -> recordExit(exit, exited));
        processManager.execute(run, events::add, exit -> recordExit(exit, exited));

        assertTrue(exited.await(5, TimeUnit.SECONDS));
        assertEquals(2, exits.size());
        assertTrue(events.stream().anyMatch(event -> event.path("message").asText().equals("execute-started")));
    }

    @Test
    void exitIsNotBlockedByDescendantsKeepingWorkerPipesOpen() throws Exception {
        writeWorker("""
                sleep 30 &
                printf '%s\\n' "$!" > child.pid
                exit 0
                """);
        Run run = run("safe-request");
        CountDownLatch exited = new CountDownLatch(1);
        try {
            processManager.plan(run, events::add, exit -> recordExit(exit, exited));

            assertTrue(exited.await(7, TimeUnit.SECONDS));
            assertEquals(0, exits.remove().exitCode());
        } finally {
            Path childPid = tempDir.resolve("child.pid");
            if (Files.exists(childPid)) {
                long pid = Long.parseLong(Files.readString(childPid).trim());
                ProcessHandle.of(pid).ifPresent(ProcessHandle::destroyForcibly);
            }
        }
    }

    private Run run(String request) throws Exception {
        Path runDir = Files.createDirectories(tempDir.resolve(UUID.randomUUID().toString()));
        return new Run(UUID.randomUUID().toString(), request, false, runDir);
    }

    private void writeWorker(String content) throws Exception {
        Files.writeString(tempDir.resolve("fleet_worker.py"), content);
    }

    private void recordExit(ProcessExit exit, CountDownLatch latch) {
        exits.add(exit);
        latch.countDown();
    }

    private void awaitFile(Path path) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
        while (!Files.exists(path) && System.nanoTime() < deadline) {
            Thread.sleep(10);
        }
        assertTrue(Files.exists(path), "O worker falso não iniciou dentro do prazo.");
    }
}
