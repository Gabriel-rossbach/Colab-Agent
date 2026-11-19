package com.colabfleet.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.colabfleet.config.FleetProperties;
import com.colabfleet.exception.ArtifactAccessException;
import com.colabfleet.exception.RunConflictException;
import com.colabfleet.model.ArtifactsResponse;
import com.colabfleet.model.Run;
import com.colabfleet.model.RunResponse;
import com.colabfleet.model.RunState;
import com.colabfleet.process.ProcessExit;
import com.colabfleet.process.WorkerCommand;
import com.colabfleet.process.WorkerProcessManager;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.function.Consumer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;

class RunServiceTest {

    @TempDir
    Path tempDir;

    private ObjectMapper objectMapper;
    private WorkerProcessManager processManager;
    private RunService runService;

    @BeforeEach
    void setUp() {
        FleetProperties properties = new FleetProperties();
        properties.setRunsDir(tempDir);
        properties.setRepoRoot("..");
        objectMapper = new ObjectMapper();
        processManager = mock(WorkerProcessManager.class);
        runService = new RunService(properties, objectMapper, processManager);
    }

    @Test
    void completesPlanningConfirmationAndExecution() throws Exception {
        RunResponse created = runService.create("pesquisar carros elétricos", true);
        assertEquals(RunState.PLANNING, created.state());
        assertTrue(created.browserEnabled());
        assertNull(created.plan());
        assertNull(created.result());
        assertNull(created.error());

        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        planning.events().accept(json("""
                {"type":"plan.ready","plan":{"request":"pesquisar carros elétricos","tasks":[{"cpu":1,"task":1,"prompt":"Use web_search para pesquisar carros elétricos."}]}}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));

        RunResponse waiting = runService.find(created.id());
        assertEquals(RunState.WAITING_CONFIRMATION, waiting.state());
        assertEquals(1, waiting.plan().tasks().size());
        assertEquals(1, waiting.plan().tasks().getFirst().cpu());

        RunResponse executing = runService.confirm(created.id());
        assertEquals(RunState.EXECUTING, executing.state());
        CapturedStart execution = captureStart(WorkerCommand.EXECUTE);
        execution.events().accept(json("""
                {"type":"run.result","result":{"totalTasks":1,"completedTasks":1,"successful":1,"gatePass":true}}
                """));
        assertNull(runService.find(created.id()).result());
        execution.events().accept(json("""
                {"type":"run.state","state":"COMPLETED"}
                """));

        RunResponse completed = runService.find(created.id());
        assertEquals(RunState.COMPLETED, completed.state());
        assertEquals(1, completed.result().totalTasks());
        assertEquals(1, completed.result().completedTasks());
        assertEquals(1, completed.result().successful());
        assertEquals(Boolean.TRUE, completed.result().gatePass());
    }

    @Test
    void rejectsSecondActiveRun() throws Exception {
        runService.create("pesquisar notícias", false);
        assertThrows(RunConflictException.class, () -> runService.create("outra pesquisa", false));
        verify(processManager, times(1)).plan(any(), any(), any());
    }

    @Test
    void numbersEventsAndSupportsIncrementalPolling() throws Exception {
        RunResponse created = runService.create("pesquisar fontes", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        planning.events().accept(json("""
                {"type":"log","machine":"cpu1","message":"Iniciando"}
                """));
        planning.events().accept(json("""
                {"type":"task.state","machine":"cpu1","task":1,"attempt":1,"state":"RUNNING"}
                """));
        planning.events().accept(json("""
                {"type":"log","message":"Concluído","timestamp":"2026-01-01T00:00:00Z"}
                """));

        List<ObjectNode> all = runService.events(created.id(), 0);
        assertEquals(3, all.size());
        assertEquals(1, all.get(0).path("seq").asInt());
        assertEquals(2, all.get(1).path("seq").asInt());
        assertNotNull(all.get(0).path("timestamp").asText());
        assertEquals("2026-01-01T00:00:00Z", all.get(2).path("timestamp").asText());

        List<ObjectNode> incremental = runService.events(created.id(), 2);
        assertEquals(1, incremental.size());
        assertEquals(3, incremental.getFirst().path("seq").asInt());
    }

    @Test
    void cancellationIsCooperativeAndIdempotentWithoutProcess() throws Exception {
        RunResponse created = runService.create("pesquisar mercado", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        planning.events().accept(json("""
                {"type":"plan.ready","plan":{"request":"pesquisar mercado","tasks":[{"cpu":1,"task":1,"prompt":"Pesquisar mercado."}]}}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));
        when(processManager.cancel(created.id())).thenReturn(false);

        RunResponse cancelled = runService.cancel(created.id());
        assertEquals(RunState.CANCELLED, cancelled.state());
        assertTrue(Files.exists(planning.run().getRunDir().resolve("cancel.requested")));
        assertEquals(RunState.CANCELLED, runService.cancel(created.id()).state());
        verify(processManager, times(1)).cancel(created.id());
    }

    @Test
    void forcedWorkerExitFinishesCancellation() throws Exception {
        RunResponse created = runService.create("pesquisar ciência", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        when(processManager.cancel(created.id())).thenReturn(true);

        assertEquals(RunState.CANCELLING, runService.cancel(created.id()).state());
        planning.exit().accept(new ProcessExit(created.id(), WorkerCommand.PLAN, 143));
        assertEquals(RunState.CANCELLED, runService.find(created.id()).state());
    }

    @Test
    void readsArtifactsAndReturnsEmptyValuesBeforeTheyExist() throws Exception {
        RunResponse created = runService.create("pesquisar tecnologia", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);

        ArtifactsResponse empty = runService.artifacts(created.id());
        assertEquals("", empty.summary());
        assertTrue(empty.results().isEmpty());

        Files.writeString(planning.run().getRunDir().resolve("summary.md"), "# Resumo\n");
        Files.writeString(planning.run().getRunDir().resolve("results.json"), "[{\"sucesso\":true}]");
        ArtifactsResponse artifacts = runService.artifacts(created.id());
        assertEquals("# Resumo\n", artifacts.summary());
        assertEquals(1, artifacts.results().size());
        assertTrue(artifacts.results().get(0).path("sucesso").asBoolean());
    }

    @Test
    void ignoresLatePlanningEventsAfterExecutionStarts() throws Exception {
        RunResponse created = runService.create("pesquisar energia", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        planning.events().accept(json("""
                {"type":"plan.ready","plan":{"request":"pesquisar energia","tasks":[{"cpu":1,"task":1,"prompt":"Pesquisar energia."}]}}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));
        runService.confirm(created.id());
        captureStart(WorkerCommand.EXECUTE);
        int eventCount = runService.events(created.id(), 0).size();

        planning.events().accept(json("""
                {"type":"log","message":"evento atrasado do planejamento"}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));

        assertEquals(RunState.EXECUTING, runService.find(created.id()).state());
        assertEquals(eventCount, runService.events(created.id(), 0).size());
    }

    @Test
    void cancellationCannotBeOverriddenByWorkerCompletionOrFailure() throws Exception {
        RunResponse created = runService.create("pesquisar oceanos", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        when(processManager.cancel(created.id())).thenReturn(true);
        assertEquals(RunState.CANCELLING, runService.cancel(created.id()).state());

        planning.events().accept(json("""
                {"type":"run.state","state":"COMPLETED"}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"FAILED","message":"falha tardia"}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"ESTADO_INVALIDO"}
                """));
        assertEquals(RunState.CANCELLING, runService.find(created.id()).state());

        planning.events().accept(json("""
                {"type":"run.state","state":"CANCELLED"}
                """));
        assertEquals(RunState.CANCELLED, runService.find(created.id()).state());
    }

    @Test
    void redactsSecretsFromEventsAndArtifacts() throws Exception {
        String request = "pesquisar segurança NVIDIA_API_KEY=segredo-da-request nvapi-token-request Bearer bearer-request";
        RunResponse created = runService.create(request, false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        assertEquals(request, planning.run().getRequest());
        assertFalse(created.request().contains("segredo-da-request"));
        assertFalse(created.request().contains("nvapi-token-request"));
        assertFalse(created.request().contains("bearer-request"));
        planning.events().accept(json("""
                {"type":"log","message":"NVIDIA_API_KEY=segredo-do-evento","NVIDIA_API_KEY":"segredo-do-campo"}
                """));
        Files.writeString(planning.run().getRunDir().resolve("summary.md"),
                "NVIDIA_API_KEY=\"segredo com espaços\" nvapi-token-artefato Bearer bearer-artefato");
        Files.writeString(planning.run().getRunDir().resolve("results.json"), """
                [{"NVIDIA_API_KEY":"segredo-do-resultado","message":"OTHER_TOKEN=token-secreto"}]
                """);

        String events = runService.events(created.id(), 0).toString();
        ArtifactsResponse artifacts = runService.artifacts(created.id());
        String serializedArtifacts = artifacts.toString();

        assertFalse(events.contains("segredo-do-evento"));
        assertFalse(events.contains("segredo-do-campo"));
        assertFalse(serializedArtifacts.contains("segredo com espaços"));
        assertFalse(serializedArtifacts.contains("segredo-do-resultado"));
        assertFalse(serializedArtifacts.contains("token-secreto"));
        assertFalse(serializedArtifacts.contains("nvapi-token-artefato"));
        assertFalse(serializedArtifacts.contains("bearer-artefato"));
        assertTrue(events.contains("[OCULTO]"));
        assertTrue(serializedArtifacts.contains("[OCULTO]"));
    }

    @Test
    void limitsArtifactSizeAndRejectsSymbolicLinks() throws Exception {
        RunResponse created = runService.create("pesquisar artefatos", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        Path summary = planning.run().getRunDir().resolve("summary.md");
        Files.writeString(summary, "x".repeat(1_000_001));
        assertThrows(ArtifactAccessException.class, () -> runService.artifacts(created.id()));

        Files.delete(summary);
        Path privateFile = Files.writeString(tempDir.resolve("private.txt"), "conteúdo privado");
        Files.createSymbolicLink(summary, privateFile);

        assertThrows(ArtifactAccessException.class, () -> runService.artifacts(created.id()));
    }

    @Test
    void limitsEachEventPollingResponseToFiveHundredItems() throws Exception {
        RunResponse created = runService.create("pesquisar eventos", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        ObjectNode event = json("""
                {"type":"log","message":"evento"}
                """);
        for (int index = 0; index < 501; index++) {
            planning.events().accept(event);
        }

        List<ObjectNode> firstPage = runService.events(created.id(), 0);
        List<ObjectNode> secondPage = runService.events(created.id(), 500);

        assertEquals(500, firstPage.size());
        assertEquals(500, firstPage.getLast().path("seq").asInt());
        assertEquals(1, secondPage.size());
        assertEquals(501, secondPage.getFirst().path("seq").asInt());
    }

    @Test
    void rejectsWaitingWithoutPlan() throws Exception {
        RunResponse created = runService.create("pesquisar plano", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);

        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));

        assertEquals(RunState.FAILED, runService.find(created.id()).state());
    }

    @Test
    void rejectsCompletionWithoutResult() throws Exception {
        RunResponse created = runService.create("pesquisar resultado", false);
        CapturedStart planning = captureStart(WorkerCommand.PLAN);
        planning.events().accept(json("""
                {"type":"plan.ready","plan":{"request":"pesquisar resultado","tasks":[{"cpu":1,"task":1,"prompt":"Pesquisar resultado."}]}}
                """));
        planning.events().accept(json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));
        runService.confirm(created.id());
        CapturedStart execution = captureStart(WorkerCommand.EXECUTE);

        execution.events().accept(json("""
                {"type":"run.state","state":"COMPLETED"}
                """));

        assertEquals(RunState.FAILED, runService.find(created.id()).state());
    }

    @Test
    void startFailureIsContainedInRun() throws Exception {
        org.mockito.Mockito.doThrow(new java.io.IOException("falha simulada"))
                .when(processManager).plan(any(), any(), any());

        RunResponse response = runService.create("pesquisar economia", false);
        assertEquals(RunState.FAILED, response.state());
        assertEquals("Não foi possível iniciar o planejamento.", response.error());
        assertFalse(runService.events(response.id(), 0).isEmpty());
    }

    private CapturedStart captureStart(WorkerCommand command) throws Exception {
        ArgumentCaptor<Run> runCaptor = ArgumentCaptor.forClass(Run.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Consumer<ObjectNode>> eventCaptor = ArgumentCaptor.forClass(Consumer.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Consumer<ProcessExit>> exitCaptor = ArgumentCaptor.forClass(Consumer.class);
        if (command == WorkerCommand.PLAN) {
            verify(processManager).plan(runCaptor.capture(), eventCaptor.capture(), exitCaptor.capture());
        } else {
            verify(processManager).execute(runCaptor.capture(), eventCaptor.capture(), exitCaptor.capture());
        }
        return new CapturedStart(runCaptor.getValue(), eventCaptor.getValue(), exitCaptor.getValue());
    }

    private ObjectNode json(String json) throws Exception {
        return (ObjectNode) objectMapper.readTree(json);
    }

    private record CapturedStart(
            Run run,
            Consumer<ObjectNode> events,
            Consumer<ProcessExit> exit) {
    }
}
