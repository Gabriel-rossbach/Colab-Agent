package com.colabfleet.process;

import com.colabfleet.model.Run;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.util.function.Consumer;

public interface WorkerProcessManager {

    void plan(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) throws IOException;

    void execute(Run run, Consumer<ObjectNode> eventHandler, Consumer<ProcessExit> exitHandler) throws IOException;

    boolean cancel(String runId);
}
