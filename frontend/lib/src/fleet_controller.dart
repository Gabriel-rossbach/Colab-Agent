library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'models.dart';

String describeFleetError(Object error) {
  if (error is ApiException) return error.userMessage;
  if (error is TimeoutException) {
    return 'Tempo esgotado ao falar com o servidor.';
  }
  if (error is FormatException) {
    return 'O servidor retornou dados em um formato inesperado.';
  }
  return 'Não foi possível comunicar com o servidor. Tente novamente.';
}

class FleetController extends ChangeNotifier {
  FleetController({FleetApiClient? api}) : _api = api ?? FleetApiClient();

  final FleetApiClient _api;
  final List<FleetRun> _recentRuns = <FleetRun>[];

  FleetRun? _selectedRun;
  FleetArtifacts? _artifacts;
  FleetEventReducer _reducer = FleetEventReducer();
  Timer? _pollTimer;

  int _lastEventSeq = 0;
  int _selectionRevision = 0;
  int _authRevision = 0;
  bool _dashboardOpen = false;
  bool _pollInFlight = false;
  bool _disposed = false;
  bool _isAuthenticated = false;
  bool _isAuthenticating = false;
  bool _actionInProgress = false;
  bool _loadingRun = false;
  bool _loadingArtifacts = false;
  bool _artifactsAttempted = false;

  String? _loginError;
  String? _pollError;
  String? _runError;
  String? _actionError;
  String? _artifactsError;

  bool get isAuthenticated => _isAuthenticated;
  bool get isAuthenticating => _isAuthenticating;
  bool get actionInProgress => _actionInProgress;
  bool get loadingRun => _loadingRun;
  bool get loadingArtifacts => _loadingArtifacts;
  bool get artifactsAttempted => _artifactsAttempted;
  FleetRun? get selectedRun => _selectedRun;
  FleetArtifacts? get artifacts => _artifacts;
  String? get loginError => _loginError;
  String? get pollError => _pollError;
  String? get runError => _runError;
  String? get actionError => _actionError;
  String? get artifactsError => _artifactsError;
  List<FleetRun> get recentRuns => List<FleetRun>.unmodifiable(_recentRuns);
  List<MachineSnapshot> get machines => _reducer.machines;
  List<MachineLogEntry> get generalLogs => _reducer.generalLogs;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<bool> login(String token) async {
    final normalized = token.trim();
    if (_isAuthenticating) return false;
    if (normalized.isEmpty) {
      _loginError = 'Informe o token de acesso.';
      _notify();
      return false;
    }

    final auth = ++_authRevision;
    _isAuthenticating = true;
    _loginError = null;
    _api.clearToken();
    _notify();

    try {
      await _api.health();
      if (_disposed || auth != _authRevision) return false;
      _api.setToken(normalized);
      final runs = await _api.listRuns();
      if (_disposed || auth != _authRevision) return false;

      _isAuthenticated = true;
      _replaceRecent(runs);
      _loginError = null;
      return true;
    } catch (error) {
      if (!_disposed && auth == _authRevision) {
        _api.clearToken();
        _isAuthenticated = false;
        _loginError = describeFleetError(error);
      }
      return false;
    } finally {
      if (!_disposed && auth == _authRevision) {
        _isAuthenticating = false;
        _notify();
      }
    }
  }

  void logout({String? reason}) {
    if (_disposed) return;
    _authRevision++;
    _selectionRevision++;
    _pollTimer?.cancel();
    _pollTimer = null;
    _dashboardOpen = false;
    _api.clearToken();
    _isAuthenticated = false;
    _isAuthenticating = false;
    _actionInProgress = false;
    _loadingRun = false;
    _loadingArtifacts = false;
    _selectedRun = null;
    _artifacts = null;
    _artifactsAttempted = false;
    _recentRuns.clear();
    _resetEventState();
    _pollError = null;
    _runError = null;
    _actionError = null;
    _artifactsError = null;
    _loginError = reason;
    _notify();
  }

  void setDashboardOpen(bool open) {
    if (_disposed || _dashboardOpen == open) return;
    _dashboardOpen = open;
    _pollTimer?.cancel();
    _pollTimer = null;
    if (!open || !_isAuthenticated) return;

    _pollTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => unawaited(_poll()),
    );
    unawaited(_poll());
  }

  Future<void> refresh() => _poll();

  Future<void> selectRun(String id) async {
    if (!_isAuthenticated || _disposed) return;
    final summary = _findRecent(id);
    if (summary == null) return;

    final selection = ++_selectionRevision;
    final auth = _authRevision;
    _selectedRun = summary;
    _loadingRun = true;
    _runError = null;
    _pollError = null;
    _actionError = null;
    _artifactsError = null;
    _artifacts = null;
    _artifactsAttempted = false;
    _loadingArtifacts = false;
    _resetEventState();
    _notify();

    try {
      final detail = await _api.getRun(id);
      if (!_selectionIsCurrent(id, selection, auth)) return;
      _selectedRun = detail;
      _upsertRecent(detail);
      _notify();

      await _loadEvents(id, selection, auth);
      final current = _selectedRun;
      if (_selectionIsCurrent(id, selection, auth) &&
          current != null &&
          (current.isTerminal || current.result != null)) {
        await _loadArtifacts(id, selection, auth);
      }
    } catch (error) {
      if (!_selectionIsCurrent(id, selection, auth)) return;
      if (error is ApiException && error.isUnauthorized) {
        _handleUnauthorized(auth);
        return;
      }
      _runError = describeFleetError(error);
    } finally {
      if (_selectionIsCurrent(id, selection, auth)) {
        _loadingRun = false;
        _notify();
      }
    }
  }

  Future<void> createRun(String request, bool browserEnabled) async {
    if (_actionInProgress || !_isAuthenticated || _disposed) return;
    final normalized = request.trim();
    if (normalized.isEmpty) {
      _actionError = 'Descreva a missão antes de gerar o plano.';
      _notify();
      return;
    }

    final auth = _authRevision;
    final selectionBeforeRequest = _selectionRevision;
    _actionInProgress = true;
    _actionError = null;
    _notify();

    try {
      final created = await _api.createRun(
        request: normalized,
        browserEnabled: browserEnabled,
      );
      if (!_authIsCurrent(auth)) return;
      _upsertRecent(created);
      _notify();

      // Não rouba a seleção caso o usuário tenha aberto outra run nesse meio-tempo.
      if (selectionBeforeRequest == _selectionRevision) {
        await selectRun(created.id);
      }
    } catch (error) {
      if (!_authIsCurrent(auth)) return;
      if (error is ApiException && error.isUnauthorized) {
        _handleUnauthorized(auth);
        return;
      }
      _actionError = describeFleetError(error);
    } finally {
      if (!_disposed && auth == _authRevision) {
        _actionInProgress = false;
        _notify();
      }
    }
  }

  Future<void> confirmSelected() {
    final run = _selectedRun;
    if (run == null || !run.canConfirm) {
      _actionError = run != null && run.isTerminal
          ? 'Uma run encerrada não pode ser confirmada.'
          : 'Esta run não está aguardando confirmação.';
      _notify();
      return Future<void>.value();
    }
    if (run.plan == null || run.plan!.tasks.isEmpty) {
      _actionError = 'Aguarde um plano explícito antes de confirmar a execução.';
      _notify();
      return Future<void>.value();
    }
    return _mutateSelected(run, confirm: true);
  }

  Future<void> cancelSelected() {
    final run = _selectedRun;
    if (run == null || !run.canCancel) {
      _actionError = 'Esta run não pode mais ser cancelada.';
      _notify();
      return Future<void>.value();
    }
    return _mutateSelected(run, confirm: false);
  }

  Future<void> _mutateSelected(FleetRun run, {required bool confirm}) async {
    if (_actionInProgress || !_isAuthenticated || _disposed) return;
    final id = run.id;
    final selection = _selectionRevision;
    final auth = _authRevision;
    _actionInProgress = true;
    _actionError = null;
    _notify();

    try {
      final updated = confirm
          ? await _api.confirmRun(id)
          : await _api.cancelRun(id);
      if (!_authIsCurrent(auth)) return;
      _upsertRecent(updated);
      if (_selectionIsCurrent(id, selection, auth)) {
        _selectedRun = updated;
      }
      _notify();
      if (_dashboardOpen) unawaited(_poll());
    } catch (error) {
      if (!_authIsCurrent(auth)) return;
      if (error is ApiException && error.isUnauthorized) {
        _handleUnauthorized(auth);
        return;
      }
      _actionError = describeFleetError(error);
    } finally {
      if (!_disposed && auth == _authRevision) {
        _actionInProgress = false;
        _notify();
      }
    }
  }

  Future<void> retryArtifacts() async {
    final run = _selectedRun;
    if (run == null || !_isAuthenticated || _disposed) return;
    _artifactsAttempted = false;
    _artifactsError = null;
    _notify();
    await _loadArtifacts(run.id, _selectionRevision, _authRevision);
  }

  Future<void> _loadEvents(String id, int selection, int auth) async {
    // O backend limita cada resposta a 500 itens. Continuar a partir do último
    // seq evita descartar o restante quando uma rajada ultrapassa esse limite.
    const eventPageLimit = 500;
    while (_selectionIsCurrent(id, selection, auth)) {
      final requestedAfter = _lastEventSeq;
      final events = await _api.getEvents(id, after: requestedAfter);
      if (!_selectionIsCurrent(id, selection, auth)) return;
      events.sort((left, right) => left.seq.compareTo(right.seq));

      var changed = false;
      for (final event in events) {
        if (event.seq <= _lastEventSeq) continue;
        _lastEventSeq = event.seq;
        _reducer.apply(event);
        final current = _selectedRun;
        if (current != null && current.id == id) {
          _selectedRun = current.applyEvent(event);
        }
        changed = true;
      }
      if (changed) {
        final current = _selectedRun;
        if (current != null) _upsertRecent(current);
        _notify();
      }

      if (events.length < eventPageLimit ||
          _lastEventSeq <= requestedAfter) {
        return;
      }
    }
  }

  Future<void> _loadArtifacts(String id, int selection, int auth) async {
    if (_artifactsAttempted ||
        !_selectionIsCurrent(id, selection, auth)) {
      return;
    }
    _artifactsAttempted = true;
    _loadingArtifacts = true;
    _artifactsError = null;
    _notify();

    try {
      final loaded = await _api.getArtifacts(id);
      if (!_selectionIsCurrent(id, selection, auth)) return;
      _artifacts = loaded;
    } catch (error) {
      if (!_selectionIsCurrent(id, selection, auth)) return;
      if (error is ApiException && error.isUnauthorized) {
        _handleUnauthorized(auth);
        return;
      }
      _artifactsError = describeFleetError(error);
    } finally {
      if (_selectionIsCurrent(id, selection, auth)) {
        _loadingArtifacts = false;
        _notify();
      }
    }
  }

  Future<void> _poll() async {
    if (_pollInFlight ||
        !_dashboardOpen ||
        !_isAuthenticated ||
        _disposed) {
      return;
    }
    _pollInFlight = true;
    final auth = _authRevision;
    final selection = _selectionRevision;
    final selectedId = _selectedRun?.id;

    try {
      final runs = await _api.listRuns();
      if (!_pollIsCurrent(auth)) return;
      _replaceRecent(runs);

      if (selectedId != null && selection == _selectionRevision) {
        final summary = _findRecent(selectedId);
        final current = _selectedRun;
        if (summary != null && current != null) {
          _selectedRun = _mergeSummary(summary, current);
        }
      }
      _pollError = null;
      _notify();

      if (selectedId == null ||
          !_selectionIsCurrent(selectedId, selection, auth) ||
          !_dashboardOpen) {
        return;
      }

      var current = _selectedRun;
      if (current != null && current.isActive) {
        final detail = await _api.getRun(selectedId);
        if (!_pollIsCurrent(auth) ||
            !_selectionIsCurrent(selectedId, selection, auth)) {
          return;
        }
        _selectedRun = detail;
        _upsertRecent(detail);
        _notify();
      }

      // Também drena runs recém-encerradas: o resumo pode ficar terminal antes
      // da última leitura dos eventos de máquina, logs e resultado.
      if (_pollIsCurrent(auth) &&
          _selectionIsCurrent(selectedId, selection, auth)) {
        await _loadEvents(selectedId, selection, auth);
        current = _selectedRun;
      }

      if (_pollIsCurrent(auth) &&
          _selectionIsCurrent(selectedId, selection, auth) &&
          current != null &&
          (current.isTerminal || current.result != null)) {
        await _loadArtifacts(selectedId, selection, auth);
      }
    } catch (error) {
      if (!_pollIsCurrent(auth)) return;
      if (error is ApiException && error.isUnauthorized) {
        _handleUnauthorized(auth);
        return;
      }
      _pollError = describeFleetError(error);
      _notify();
    } finally {
      _pollInFlight = false;
    }
  }

  bool _authIsCurrent(int auth) {
    return !_disposed && _isAuthenticated && auth == _authRevision;
  }

  bool _pollIsCurrent(int auth) {
    return _authIsCurrent(auth) && _dashboardOpen;
  }

  bool _selectionIsCurrent(String id, int selection, int auth) {
    return _authIsCurrent(auth) &&
        selection == _selectionRevision &&
        _selectedRun?.id == id;
  }

  void _handleUnauthorized(int auth) {
    if (!_authIsCurrent(auth)) return;
    logout(reason: 'Sua sessão expirou ou o token deixou de ser válido (401).');
  }

  void _resetEventState() {
    _reducer = FleetEventReducer();
    _lastEventSeq = 0;
  }

  FleetRun? _findRecent(String id) {
    for (final run in _recentRuns) {
      if (run.id == id) return run;
    }
    return null;
  }

  static FleetRun _mergeSummary(FleetRun summary, FleetRun current) {
    return summary.copyWith(
      plan: summary.plan ?? current.plan,
      result: summary.result ?? current.result,
      error: summary.error ?? current.error,
    );
  }

  void _replaceRecent(List<FleetRun> runs) {
    _recentRuns
      ..clear()
      ..addAll(runs);
    _sortAndLimitRecent();
  }

  void _upsertRecent(FleetRun run) {
    _recentRuns.removeWhere((item) => item.id == run.id);
    _recentRuns.add(run);
    _sortAndLimitRecent();
  }

  void _sortAndLimitRecent() {
    _recentRuns.sort((left, right) {
      final leftDate = left.sortDate;
      final rightDate = right.sortDate;
      if (leftDate != null && rightDate != null) {
        return rightDate.compareTo(leftDate);
      }
      if (leftDate != null) return -1;
      if (rightDate != null) return 1;
      return right.id.compareTo(left.id);
    });
    const maxRecentRuns = 40;
    if (_recentRuns.length > maxRecentRuns) {
      _recentRuns.removeRange(maxRecentRuns, _recentRuns.length);
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _pollTimer?.cancel();
    _pollTimer = null;
    _api.close();
    super.dispose();
  }
}
