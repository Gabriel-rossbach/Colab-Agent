library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  const ApiException({required this.message, this.statusCode});

  final String message;
  final int? statusCode;

  bool get isUnauthorized => statusCode == 401;
  bool get isServiceUnavailable => statusCode == 503;

  String get userMessage {
    if (statusCode == 401) {
      return 'Token inválido ou expirado (401).';
    }
    if (statusCode == 503) {
      return 'Serviço indisponível no momento (503). Tente novamente.';
    }
    if (statusCode == 403) {
      return 'Acesso não autorizado (403).';
    }
    if (statusCode == 404) {
      return 'Recurso não encontrado (404).';
    }
    if (message.isNotEmpty) return message;
    if (statusCode != null) {
      return 'Falha na requisição (HTTP $statusCode).';
    }
    return 'Falha na requisição.';
  }

  @override
  String toString() => 'ApiException: ${userMessage}';
}

/// Cliente HTTP enxuto. O token existe somente nesta instância em memória.
class FleetApiClient {
  FleetApiClient({http.Client? client, Uri? baseUri})
      : _client = client ?? http.Client(),
        _baseUri = _directoryUri(baseUri ?? _resolveBaseUri());

  final http.Client _client;
  final Uri _baseUri;
  String _token = '';

  static const Duration _timeout = Duration(seconds: 15);

  bool get hasToken => _token.isNotEmpty;

  void setToken(String token) {
    _token = token.trim();
  }

  void clearToken() {
    _token = '';
  }

  void close() {
    _client.close();
  }

  static Uri _resolveBaseUri() {
    const configured = String.fromEnvironment('API_BASE_URL');
    if (configured.trim().isNotEmpty) {
      final parsed = Uri.parse(configured.trim());
      return parsed.hasScheme ? parsed : Uri.base.resolveUri(parsed);
    }
    // Same-origin: usa o scheme/host/porta do próprio app, sem o caminho da rota.
    return Uri.base.replace(path: '/', query: null, fragment: null);
  }

  static Uri _directoryUri(Uri uri) {
    final path = uri.path.isEmpty || uri.path.endsWith('/')
        ? uri.path
        : '${uri.path}/';
    return uri.replace(path: path, query: null, fragment: null);
  }

  Uri _uri(String path, [Map<String, String>? queryParameters]) {
    return _baseUri.resolveUri(
      Uri(path: path, queryParameters: queryParameters),
    );
  }

  Map<String, String> _headers({required bool requiresAuth, bool hasBody = false}) {
    final headers = <String, String>{'Accept': 'application/json'};
    if (hasBody) {
      headers['Content-Type'] = 'application/json; charset=utf-8';
    }
    if (requiresAuth) {
      if (_token.isEmpty) {
        throw const ApiException(
          message: 'Informe o token de acesso antes de continuar.',
        );
      }
      headers['Authorization'] = 'Bearer $_token';
    }
    return headers;
  }

  Future<dynamic> _request(
    String method,
    String path, {
    bool requiresAuth = true,
    Object? body,
    Map<String, String>? queryParameters,
  }) async {
    final uri = _uri(path, queryParameters);
    final headers = _headers(requiresAuth: requiresAuth, hasBody: body != null);

    final http.Response response;
    try {
      final Future<http.Response> future = method == 'GET'
          ? _client.get(uri, headers: headers)
          : _client.post(
              uri,
              headers: headers,
              body: body == null ? null : jsonEncode(body),
            );
      response = await future.timeout(_timeout);
    } on TimeoutException {
      throw const ApiException(
        message: 'Tempo esgotado ao falar com o servidor.',
      );
    }

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(
        message: _safeErrorDetail(response.body),
        statusCode: response.statusCode,
      );
    }

    final text = utf8.decode(response.bodyBytes, allowMalformed: true).trim();
    if (text.isEmpty) return null;
    try {
      return jsonDecode(text);
    } on FormatException {
      throw const ApiException(
        message: 'O servidor retornou uma resposta que não é JSON válido.',
        statusCode: 200,
      );
    }
  }

  String _safeErrorDetail(String body) {
    var detail = '';
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map) {
        final value = decoded['detail'] ?? decoded['message'] ?? decoded['error'];
        if (value is String) detail = value;
      }
    } on FormatException {
      detail = '';
    }

    detail = detail
        .replaceAll(RegExp(r'Bearer\s+\S+', caseSensitive: false), '[oculto]')
        .replaceAll(RegExp(r'[\r\n\t]+'), ' ')
        .trim();
    if (_token.length >= 4) {
      detail = detail.replaceAll(_token, '[oculto]');
    }
    if (detail.length > 300) {
      detail = '${detail.substring(0, 300)}...';
    }
    return detail;
  }

  static Map<String, dynamic> _asMap(Object? value) {
    if (value is Map<String, dynamic>) return value;
    if (value is Map) return Map<String, dynamic>.from(value);
    throw const FormatException('Era esperado um objeto JSON.');
  }

  static List<dynamic> _asList(Object? value) {
    if (value is List) return value;
    throw const FormatException('Era esperado um array JSON.');
  }

  Future<Map<String, dynamic>> health() async {
    final data = _asMap(await _request('GET', 'api/health', requiresAuth: false));
    final status = data['status'];
    if (status is! String || status.toUpperCase() != 'UP') {
      throw ApiException(
        message:
            'Serviço indisponível no momento (status: ${status is String ? status : 'desconhecido'}).',
        statusCode: 503,
      );
    }
    return data;
  }

  Future<List<FleetRun>> listRuns() async {
    final data = _asList(await _request('GET', 'api/runs'));
    return data
        .map((item) => FleetRun.fromJson(_asMap(item)))
        .toList(growable: false);
  }

  Future<FleetRun> getRun(String id) async {
    final data = _asMap(await _request('GET', 'api/runs/${Uri.encodeComponent(id)}'));
    return FleetRun.fromJson(data);
  }

  Future<FleetRun> createRun({
    required String request,
    required bool browserEnabled,
  }) async {
    final data = _asMap(
      await _request(
        'POST',
        'api/runs',
        body: <String, Object?>{
          'request': request,
          'browserEnabled': browserEnabled,
        },
      ),
    );
    return FleetRun.fromJson(data);
  }

  Future<FleetRun> confirmRun(String id) => _mutateRun(id, 'confirm');

  Future<FleetRun> cancelRun(String id) => _mutateRun(id, 'cancel');

  Future<FleetRun> _mutateRun(String id, String action) async {
    final data = _asMap(
      await _request('POST', 'api/runs/${Uri.encodeComponent(id)}/$action'),
    );
    return FleetRun.fromJson(data);
  }

  Future<List<RunEvent>> getEvents(String id, {required int after}) async {
    final data = _asList(
      await _request(
        'GET',
        'api/runs/${Uri.encodeComponent(id)}/events',
        queryParameters: <String, String>{'after': after.toString()},
      ),
    );
    return data
        .map((item) => RunEvent.fromJson(_asMap(item)))
        .toList(growable: false);
  }

  Future<FleetArtifacts> getArtifacts(String id) async {
    final data = _asMap(
      await _request('GET', 'api/runs/${Uri.encodeComponent(id)}/artifacts'),
    );
    return FleetArtifacts.fromJson(data);
  }
}
