package com.colabfleet;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.colabfleet.model.Run;
import com.colabfleet.process.ProcessExit;
import com.colabfleet.process.WorkerCommand;
import com.colabfleet.process.WorkerProcessManager;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

@SpringBootTest(properties = "fleet.api-token=token-de-integracao")
@AutoConfigureMockMvc
class FleetBackendIntegrationTest {

    private static final String TOKEN = "token-de-integracao";

    @TempDir
    static Path tempDir;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private FakeWorkerProcessManager processManager;

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("fleet.runs-dir", () -> tempDir.toString());
    }

    @Test
    void completeRestFlowUsesFakeWorkerAndNeverExposesSecrets() throws Exception {
        mockMvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
        mockMvc.perform(get("/api/runs"))
                .andExpect(status().isUnauthorized());

        MvcResult createdResult = mockMvc.perform(post("/api/runs")
                        .header("Authorization", "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"request\":\"pesquisar integração\",\"browserEnabled\":true}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.state").value("PLANNING"))
                .andReturn();
        String runId = objectMapper.readTree(createdResult.getResponse().getContentAsString())
                .path("id").asText();

        processManager.emit(runId, WorkerCommand.PLAN, json("""
                {"type":"plan.ready","plan":{"request":"pesquisar integração","tasks":[{"cpu":1,"task":1,"prompt":"Pesquisar integração."}]}}
                """));
        processManager.emit(runId, WorkerCommand.PLAN, json("""
                {"type":"run.state","state":"WAITING_CONFIRMATION"}
                """));
        mockMvc.perform(get("/api/runs/{id}", runId).header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.state").value("WAITING_CONFIRMATION"))
                .andExpect(jsonPath("$.plan.tasks[0].task").value(1));

        mockMvc.perform(post("/api/runs/{id}/confirm", runId).header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.state").value("EXECUTING"));
        processManager.emit(runId, WorkerCommand.EXECUTE, json("""
                {"type":"log","message":"NVIDIA_API_KEY=segredo-da-integracao"}
                """));
        processManager.emit(runId, WorkerCommand.EXECUTE, json("""
                {"type":"run.result","result":{"totalTasks":1,"completedTasks":1,"successful":1,"gatePass":true}}
                """));
        processManager.emit(runId, WorkerCommand.EXECUTE, json("""
                {"type":"run.state","state":"COMPLETED"}
                """));

        mockMvc.perform(get("/api/runs/{id}", runId).header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.state").value("COMPLETED"))
                .andExpect(jsonPath("$.result.totalTasks").value(1))
                .andExpect(jsonPath("$.result.completedTasks").value(1))
                .andExpect(jsonPath("$.result.successful").value(1))
                .andExpect(jsonPath("$.result.gatePass").value(true));

        Path runDir = processManager.run(runId).getRunDir();
        Files.writeString(runDir.resolve("summary.md"), "# Resumo da integração\n");
        Files.writeString(runDir.resolve("results.json"), "[{\"sucesso\":true}]");
        mockMvc.perform(get("/api/runs/{id}/artifacts", runId).header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.summary").value("# Resumo da integração\n"))
                .andExpect(jsonPath("$.results[0].sucesso").value(true));

        MvcResult events = mockMvc.perform(get("/api/runs/{id}/events?after=0", runId)
                        .header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].seq").value(1))
                .andReturn();
        assertFalse(events.getResponse().getContentAsString().contains("segredo-da-integracao"));
    }

    private ObjectNode json(String content) throws Exception {
        JsonNode node = objectMapper.readTree(content);
        return (ObjectNode) node;
    }

    @TestConfiguration
    static class FakeWorkerConfiguration {

        @Bean
        @Primary
        FakeWorkerProcessManager fakeWorkerProcessManager() {
            return new FakeWorkerProcessManager();
        }
    }

    static final class FakeWorkerProcessManager implements WorkerProcessManager {

        private final Map<String, Registration> registrations = new ConcurrentHashMap<>();

        @Override
        public void plan(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) {
            registrations.put(run.getId(), new Registration(run, eventHandler));
        }

        @Override
        public void execute(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) {
            registrations.put(run.getId(), new Registration(run, eventHandler));
        }

        @Override
        public boolean cancel(String runId) {
            return false;
        }

        void emit(String runId, WorkerCommand command, ObjectNode event) {
            registrations.get(runId).eventHandler().accept(event);
        }

        Run run(String runId) {
            return registrations.get(runId).run();
        }

        private record Registration(Run run, Consumer<ObjectNode> eventHandler) {
        }
    }
}
