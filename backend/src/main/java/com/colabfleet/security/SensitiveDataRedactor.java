package com.colabfleet.security;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.TextNode;
import java.util.Iterator;
import java.util.Map;
import java.util.regex.Pattern;

public final class SensitiveDataRedactor {

    private static final String REDACTED = "[OCULTO]";
    private static final String SECRET_NAME =
            "(?:NVIDIA_API_KEY|[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY))";
    private static final Pattern SECRET_FIELD_PATTERN = Pattern.compile("(?i)^" + SECRET_NAME + "$");
    private static final Pattern QUOTED_SECRET_PATTERN = Pattern.compile(
            "(?i)(\\b" + SECRET_NAME + "\\b[\"']?\\s*[=:]\\s*)([\"'])(.*?)\\2");
    private static final Pattern UNQUOTED_SECRET_PATTERN = Pattern.compile(
            "(?i)(\\b" + SECRET_NAME + "\\b\\s*[=:]\\s*)(?![\"'])[^\\s,;\"']+");
    private static final Pattern BEARER_PATTERN = Pattern.compile(
            "(?i)(\\bBearer\\s+)[^\\s,;\"']+");
    private static final Pattern NVIDIA_TOKEN_PATTERN = Pattern.compile(
            "(?i)\\bnvapi-[A-Z0-9_-]+");

    private SensitiveDataRedactor() {
    }

    public static String redact(String value) {
        if (value == null || value.isEmpty()) {
            return value;
        }
        String redacted = QUOTED_SECRET_PATTERN.matcher(value)
                .replaceAll("$1$2" + REDACTED + "$2");
        redacted = UNQUOTED_SECRET_PATTERN.matcher(redacted).replaceAll("$1" + REDACTED);
        redacted = BEARER_PATTERN.matcher(redacted).replaceAll("$1" + REDACTED);
        return NVIDIA_TOKEN_PATTERN.matcher(redacted).replaceAll(REDACTED);
    }

    @SuppressWarnings("unchecked")
    public static <T extends JsonNode> T redactJson(T value) {
        if (value == null) {
            return null;
        }
        return (T) redactNode(value.deepCopy());
    }

    private static JsonNode redactNode(JsonNode node) {
        if (node.isObject()) {
            Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
            while (fields.hasNext()) {
                Map.Entry<String, JsonNode> field = fields.next();
                if (SECRET_FIELD_PATTERN.matcher(field.getKey()).matches()) {
                    field.setValue(TextNode.valueOf(REDACTED));
                } else {
                    field.setValue(redactNode(field.getValue()));
                }
            }
        } else if (node.isArray()) {
            ArrayNode array = (ArrayNode) node;
            for (int index = 0; index < array.size(); index++) {
                array.set(index, redactNode(array.get(index)));
            }
        } else if (node.isTextual()) {
            return TextNode.valueOf(redact(node.textValue()));
        }
        return node;
    }
}
