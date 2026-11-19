package com.colabfleet.model;

import com.fasterxml.jackson.databind.node.ArrayNode;

public record ArtifactsResponse(String summary, ArrayNode results) {
}
