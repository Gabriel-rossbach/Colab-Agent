package com.colabfleet.model;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;

class RunTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void retainsOnlyTheMostRecentTenThousandEventsWithoutReusingSequences() {
        Run run = new Run("run-1", "request", false, Path.of("run-dir"));
        for (int index = 0; index < 10_005; index++) {
            ObjectNode event = objectMapper.createObjectNode();
            event.put("type", "log");
            event.put("message", "evento-" + index);
            run.addEvent(event);
        }

        List<ObjectNode> events = run.eventsAfter(0, 20_000);

        assertEquals(10_000, events.size());
        assertEquals(6, events.getFirst().path("seq").asInt());
        assertEquals("evento-5", events.getFirst().path("message").asText());
        assertEquals(10_005, events.getLast().path("seq").asInt());
    }

    @Test
    void responseRedactsRequestAndErrorWithoutChangingTheWorkerRequest() {
        String request = "NVIDIA_API_KEY=segredo-da-request nvapi-token-solto Bearer token-bearer";
        Run run = new Run("run-1", request, false, Path.of("run-dir"));
        run.fail("Falha com nvapi-token-do-erro e Bearer outro-token");

        RunResponse response = run.toResponse();

        assertEquals(request, run.getRequest());
        assertFalse(response.request().contains("segredo-da-request"));
        assertFalse(response.request().contains("nvapi-token-solto"));
        assertFalse(response.request().contains("token-bearer"));
        assertFalse(response.error().contains("nvapi-token-do-erro"));
        assertFalse(response.error().contains("outro-token"));
        assertTrue(response.request().contains("NVIDIA_API_KEY=[OCULTO]"));
        assertTrue(response.request().contains("Bearer [OCULTO]"));
        assertTrue(response.error().contains("Bearer [OCULTO]"));
    }

    @Test
    void returnedEventsCannotMutateTheStoredEvent() {
        Run run = new Run("run-1", "request", false, Path.of("run-dir"));
        ObjectNode event = objectMapper.createObjectNode();
        event.put("type", "log");
        event.put("message", "original");

        ObjectNode returned = run.addEvent(event);
        returned.put("message", "alterado");
        event.put("message", "também alterado");

        assertEquals("original", run.eventsAfter(0, 1).getFirst().path("message").asText());
    }
}
