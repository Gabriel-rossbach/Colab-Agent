package com.colabfleet.config;

import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "fleet")
public class FleetProperties {

    private String repoRoot = "..";
    private String pythonBin = "python3";
    private Path runsDir = Path.of("/tmp/colab-fleet-runs");
    private String apiToken = "";
    private String corsAllowedOrigins = "http://localhost:5173,http://localhost:8080";

    public String getRepoRoot() {
        return repoRoot;
    }

    public void setRepoRoot(String repoRoot) {
        this.repoRoot = repoRoot;
    }

    public String getPythonBin() {
        return pythonBin;
    }

    public void setPythonBin(String pythonBin) {
        this.pythonBin = pythonBin;
    }

    public Path getRunsDir() {
        return runsDir;
    }

    public void setRunsDir(Path runsDir) {
        this.runsDir = runsDir;
    }

    public String getApiToken() {
        return apiToken;
    }

    public void setApiToken(String apiToken) {
        this.apiToken = apiToken;
    }

    public String getCorsAllowedOrigins() {
        return corsAllowedOrigins;
    }

    public void setCorsAllowedOrigins(String corsAllowedOrigins) {
        this.corsAllowedOrigins = corsAllowedOrigins;
    }

    public List<String> origensPermitidas() {
        return Arrays.stream(corsAllowedOrigins.split(","))
                .map(String::trim)
                .filter(origem -> !origem.isEmpty())
                .toList();
    }
}
