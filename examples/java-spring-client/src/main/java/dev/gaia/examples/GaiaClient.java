package dev.gaia.examples;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.web.client.RestClient;

public final class GaiaClient {
    private final RestClient http;

    public GaiaClient(String baseUrl, String apiKey) {
        this.http = RestClient.builder()
                .baseUrl(baseUrl)
                .defaultHeader("X-Gaia-Api-Key", apiKey)
                .build();
    }

    public Map<?, ?> createRun(String text, String userId, String organization, List<String> roles) {
        Map<String, Object> body = Map.of(
                "scenario_id", "controlled-task",
                "mode", "mock",
                "user", Map.of("id", userId, "organization", organization, "roles", roles),
                "request", Map.of("text", text));
        return http.post()
                .uri("/v1/runs")
                .header("Idempotency-Key", UUID.randomUUID().toString())
                .body(body)
                .retrieve()
                .body(Map.class);
    }

    public Map<?, ?> getRun(String runId) {
        return http.get().uri("/v1/runs/{runId}", runId).retrieve().body(Map.class);
    }
}
