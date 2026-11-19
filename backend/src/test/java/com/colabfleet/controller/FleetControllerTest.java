package com.colabfleet.controller;

import static org.hamcrest.Matchers.nullValue;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.colabfleet.config.FleetProperties;
import com.colabfleet.exception.RunConflictException;
import com.colabfleet.exception.RunNotFoundException;
import com.colabfleet.model.ArtifactsResponse;
import com.colabfleet.model.RunResponse;
import com.colabfleet.model.RunState;
import com.colabfleet.security.ApiAuthenticationFilter;
import com.colabfleet.service.RunService;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class FleetControllerTest {

    private static final String TOKEN = "token-de-teste";

    private FleetProperties properties;
    private ObjectMapper objectMapper;
    private RunService runService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        properties = new FleetProperties();
        properties.setApiToken(TOKEN);
        objectMapper = new ObjectMapper();
        runService = mock(RunService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new FleetController(runService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .addFilters(new ApiAuthenticationFilter(properties, objectMapper))
                .build();
    }

    @Test
    void healthIsPublicEvenWithoutConfiguredToken() throws Exception {
        properties.setApiToken("");
        mockMvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"status\":\"UP\"}"));
    }

    @Test
    void protectedEndpointsReportMissingServerConfiguration() throws Exception {
        properties.setApiToken("");
        mockMvc.perform(get("/api/runs"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error").value("Autenticação não configurada no servidor."));
        verifyNoInteractions(runService);
    }

    @Test
    void protectedEndpointsRejectMissingOrWrongToken() throws Exception {
        mockMvc.perform(get("/api"))
                .andExpect(status().isUnauthorized());
        mockMvc.perform(get("/api/runs"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").exists());
        mockMvc.perform(get("/api/runs").header("Authorization", "Bearer incorreto"))
                .andExpect(status().isUnauthorized());
        verifyNoInteractions(runService);
    }

    @Test
    void protectedEndpointsAcceptValidToken() throws Exception {
        when(runService.list()).thenReturn(List.of());
        mockMvc.perform(get("/api/runs").header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
    }

    @Test
    void createsRunWithAcceptedStatusAndExactFields() throws Exception {
        RunResponse response = response(RunState.PLANNING);
        when(runService.create("pesquisar carros", true)).thenReturn(response);

        mockMvc.perform(post("/api/runs")
                        .header("Authorization", "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"request\":\"pesquisar carros\",\"browserEnabled\":true}"))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.id").value("run-1"))
                .andExpect(jsonPath("$.request").value("pesquisar carros"))
                .andExpect(jsonPath("$.browserEnabled").value(true))
                .andExpect(jsonPath("$.state").value("PLANNING"))
                .andExpect(jsonPath("$.plan").value(nullValue()))
                .andExpect(jsonPath("$.result").value(nullValue()))
                .andExpect(jsonPath("$.error").value(nullValue()))
                .andExpect(jsonPath("$.createdAt").value("2026-01-01T00:00:00Z"))
                .andExpect(jsonPath("$.updatedAt").value("2026-01-01T00:00:00Z"));
    }

    @Test
    void validatesRequestBeforeCallingService() throws Exception {
        mockMvc.perform(post("/api/runs")
                        .header("Authorization", "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"request\":\"oi\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.error").value("A solicitação deve ter entre 3 e 10000 caracteres."));
        verifyNoInteractions(runService);
    }

    @Test
    void mapsNotFoundAndConflictToJsonErrors() throws Exception {
        when(runService.find("ausente")).thenThrow(new RunNotFoundException());
        mockMvc.perform(get("/api/runs/ausente").header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("Execução não encontrada."));

        when(runService.create("pesquisa válida", false))
                .thenThrow(new RunConflictException("Já existe uma execução ativa."));
        mockMvc.perform(post("/api/runs")
                        .header("Authorization", "Bearer " + TOKEN)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"request\":\"pesquisa válida\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error").value("Já existe uma execução ativa."));
    }

    @Test
    void returnsEventArrayAndEmptyArtifacts() throws Exception {
        ObjectNode event = objectMapper.createObjectNode();
        event.put("type", "log");
        event.put("message", "Iniciando");
        event.put("seq", 13);
        event.put("timestamp", "2026-01-01T00:00:00Z");
        when(runService.events(eq("run-1"), anyLong())).thenReturn(List.of(event));
        when(runService.artifacts("run-1"))
                .thenReturn(new ArtifactsResponse("", objectMapper.createArrayNode()));

        mockMvc.perform(get("/api/runs/run-1/events?after=12").header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].seq").value(13));
        verify(runService).events("run-1", 12);

        mockMvc.perform(get("/api/runs/run-1/artifacts").header("Authorization", "Bearer " + TOKEN))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"summary\":\"\",\"results\":[]}"));
    }

    private RunResponse response(RunState state) {
        return new RunResponse(
                "run-1",
                "pesquisar carros",
                true,
                state,
                null,
                null,
                null,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z");
    }
}
