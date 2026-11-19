package com.colabfleet.model;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record CreateRunRequest(
        @NotBlank(message = "A solicitação é obrigatória.")
        @Size(min = 3, max = 10000, message = "A solicitação deve ter entre 3 e 10000 caracteres.")
        String request,
        boolean browserEnabled) {
}
