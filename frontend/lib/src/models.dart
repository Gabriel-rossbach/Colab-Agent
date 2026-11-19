library;

String _string(Object? value, [String fallback = '']) {
  if (value == null) return fallback;
  if (value is String) return value;
  if (value is num || value is bool) return value.toString();
  return fallback;
}

String? _nullableString(Object? value) {
  if (value == null) return null;
  final text = _string(value);
  return text.isEmpty ? null : text;
}

int _int(Object? value, [int fallback = 0]) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(_string(value)) ?? fallback;
}

int? _nullableInt(Object? value) {
  if (value == null) return null;
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse(_string(value));
}

bool _bool(Object? value, [bool fallback = false]) {
  if (value is bool) return value;
  if (value is num) return value != 0;
  final text = _string(value).toLowerCase();
  if (text == 'true' || text == '1' || text == 'yes') return true;
  if (text == 'false' || text == '0' || text == 'no') return false;
  return fallback;
}

bool? _nullableBool(Object? value) {
  if (value == null) return null;
  if (value is bool) return value;
  if (value is num) return value != 0;
  final text = _string(value).toLowerCase();
  if (text == 'true' || text == '1' || text == 'yes') return true;
  if (text == 'false' || text == '0' || text == 'no') return false;
  return null;
}

Map<String, dynamic>? _mapOrNull(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) return Map<String, dynamic>.from(value);
  return null;
}

DateTime? _dateOrNull(Object? value) {
  final text = _nullableString(value);
  return text == null ? null : DateTime.tryParse(text);
}

class PlanTask {
  const PlanTask({
    required this.cpu,
    required this.task,
    required this.prompt,
  });

  factory PlanTask.fromJson(Map<String, dynamic> json) {
    return PlanTask(
      cpu: _string(json['cpu']),
      task: _string(json['task']),
      prompt: _string(json['prompt']),
    );
  }

  final String cpu;
  final String task;
  final String prompt;
}

class RunPlan {
  const RunPlan({required this.request, required this.tasks});

  factory RunPlan.fromJson(Map<String, dynamic> json) {
    final rawTasks = json['tasks'];
    return RunPlan(
      request: _string(json['request']),
      tasks: rawTasks is List
          ? rawTasks
              .map(_mapOrNull)
              .whereType<Map<String, dynamic>>()
              .map(PlanTask.fromJson)
              .toList(growable: false)
          : const <PlanTask>[],
    );
  }

  final String request;
  final List<PlanTask> tasks;
}

class RunResult {
  const RunResult({required this.totalTasks, required this.successful});

  factory RunResult.fromJson(Map<String, dynamic> json) {
    return RunResult(
      totalTasks: _int(json['totalTasks']),
      successful: _int(json['successful']),
    );
  }

  final int totalTasks;
  final int successful;
}

class RunEvent {
  const RunEvent({
    required this.seq,
    required this.type,
    this.timestamp = '',
    this.data = const <String, dynamic>{},
  });

  factory RunEvent.fromJson(Map<String, dynamic> json) {
    return RunEvent(
      seq: _int(json['seq']),
      type: _string(json['type']),
      timestamp: _string(json['timestamp']),
      data: json,
    );
  }

  final int seq;
  final String type;
  final String timestamp;
  final Map<String, dynamic> data;

  String? get state => _nullableString(data['state']);
  String? get message => _nullableString(data['message']);
  String? get machine => _nullableString(data['machine']);
  String? get task => _nullableString(data['task']);
  int? get attempt => _nullableInt(data['attempt']);
  DateTime? get date => _dateOrNull(timestamp);

  RunPlan? get plan {
    final value = _mapOrNull(data['plan']);
    return value == null ? null : RunPlan.fromJson(value);
  }

  RunResult? get result {
    final value = _mapOrNull(data['result']);
    return value == null ? null : RunResult.fromJson(value);
  }
}

class FleetRun {
  const FleetRun({
    required this.id,
    required this.request,
    required this.browserEnabled,
    required this.state,
    required this.plan,
    required this.result,
    required this.error,
    required this.createdAt,
    required this.updatedAt,
  });

  factory FleetRun.fromJson(Map<String, dynamic> json) {
    final plan = _mapOrNull(json['plan']);
    final result = _mapOrNull(json['result']);
    return FleetRun(
      id: _string(json['id']),
      request: _string(json['request']),
      browserEnabled: _bool(json['browserEnabled']),
      state: _string(json['state'], 'UNKNOWN').toUpperCase(),
      plan: plan == null ? null : RunPlan.fromJson(plan),
      result: result == null ? null : RunResult.fromJson(result),
      error: _nullableString(json['error']),
      createdAt: _dateOrNull(json['createdAt']),
      updatedAt: _dateOrNull(json['updatedAt']),
    );
  }

  final String id;
  final String request;
  final bool browserEnabled;
  final String state;
  final RunPlan? plan;
  final RunResult? result;
  final String? error;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  static bool isTerminalState(String value) =>
      value == 'COMPLETED' || value == 'FAILED' || value == 'CANCELLED';

  bool get isTerminal => isTerminalState(state);

  bool get isActive => !isTerminal;

  bool get canConfirm => state == 'WAITING_CONFIRMATION';

  bool get canCancel =>
      state == 'PLANNING' ||
      state == 'WAITING_CONFIRMATION' ||
      state == 'EXECUTING';

  DateTime? get sortDate => updatedAt ?? createdAt;

  FleetRun copyWith({
    String? state,
    RunPlan? plan,
    RunResult? result,
    String? error,
    DateTime? updatedAt,
  }) {
    return FleetRun(
      id: id,
      request: request,
      browserEnabled: browserEnabled,
      state: state ?? this.state,
      plan: plan ?? this.plan,
      result: result ?? this.result,
      error: error ?? this.error,
      createdAt: createdAt,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }

  FleetRun applyEvent(RunEvent event) {
    switch (event.type) {
      case 'run.state':
        final nextState = event.state?.toUpperCase();
        if (nextState == null) return this;
        // O detalhe da run e o backend impedem regressões; os eventos também
        // precisam dessa proteção porque podem chegar após confirm/cancel.
        if (isTerminal ||
            (state == 'CANCELLING' && !isTerminalState(nextState))) {
          return this;
        }
        return copyWith(
          state: nextState,
          error: event.message,
          updatedAt: event.date,
        );
      case 'plan.ready':
        final nextPlan = event.plan;
        return nextPlan == null ? this : copyWith(plan: nextPlan);
      case 'run.result':
        final nextResult = event.result;
        return nextResult == null ? this : copyWith(result: nextResult);
      default:
        return this;
    }
  }
}

class ArtifactResult {
  const ArtifactResult({
    required this.machine,
    required this.task,
    required this.prompt,
    required this.success,
    required this.rawOutput,
    required this.fullOutput,
    required this.error,
    required this.attempts,
  });

  factory ArtifactResult.fromJson(Map<String, dynamic> json) {
    return ArtifactResult(
      machine: _string(json['maquina']),
      task: _string(json['task']),
      prompt: _string(json['prompt']),
      success: _nullableBool(json['sucesso']),
      rawOutput: _nullableString(json['saida_bruta']),
      fullOutput: _nullableString(json['saida_completa']),
      error: _nullableString(json['erro']),
      attempts: _nullableInt(json['tentativas']),
    );
  }

  final String machine;
  final String task;
  final String prompt;
  final bool? success;
  final String? rawOutput;
  final String? fullOutput;
  final String? error;
  final int? attempts;

  /// Nunca privilegia o recorte quando o worker forneceu a saída integral.
  String? get output => fullOutput ?? rawOutput;
  bool get hasFullOutput => fullOutput != null;
}

class FleetArtifacts {
  const FleetArtifacts({required this.summary, required this.results});

  factory FleetArtifacts.fromJson(Map<String, dynamic> json) {
    final rawResults = json['results'];
    return FleetArtifacts(
      summary: _string(json['summary']),
      results: rawResults is List
          ? rawResults
              .map(_mapOrNull)
              .whereType<Map<String, dynamic>>()
              .map(ArtifactResult.fromJson)
              .toList(growable: false)
          : const <ArtifactResult>[],
    );
  }

  final String summary;
  final List<ArtifactResult> results;
}

class MachineLogEntry {
  const MachineLogEntry({
    required this.seq,
    required this.timestamp,
    required this.message,
    this.machine,
    this.task,
  });

  final int seq;
  final String timestamp;
  final String message;
  final String? machine;
  final String? task;
}

class MachineSnapshot {
  MachineSnapshot({
    required this.name,
    this.state = 'IDLE',
    this.task,
    this.taskState,
    this.attempt,
    this.lastMessage,
    List<MachineLogEntry> logs = const <MachineLogEntry>[],
  }) : logs = List<MachineLogEntry>.unmodifiable(logs);

  final String name;
  final String state;
  final String? task;
  final String? taskState;
  final int? attempt;
  final String? lastMessage;
  final List<MachineLogEntry> logs;

  bool get isPlanner => name == 'cpu6';
}

/// Reduz somente eventos estruturados. Logs nunca são interpretados como estado.
class FleetEventReducer {
  FleetEventReducer()
      : _machines = List<MachineSnapshot>.generate(
          6,
          (index) => MachineSnapshot(name: 'cpu${index + 1}'),
          growable: false,
        );

  static const int maxLogsPerMachine = 500;

  final List<MachineSnapshot> _machines;
  final List<MachineLogEntry> _generalLogs = <MachineLogEntry>[];

  List<MachineSnapshot> get machines =>
      List<MachineSnapshot>.unmodifiable(_machines);
  List<MachineLogEntry> get generalLogs =>
      List<MachineLogEntry>.unmodifiable(_generalLogs);

  void apply(RunEvent event) {
    switch (event.type) {
      case 'machine.state':
        _applyMachineState(event);
      case 'task.state':
        _applyTaskState(event);
      case 'log':
        _applyLog(event);
    }
  }

  void _applyMachineState(RunEvent event) {
    final index = _machineIndex(event.machine);
    if (index == -1) return;
    final current = _machines[index];
    final nextState = event.state?.toUpperCase() ?? current.state;
    final eventTask = event.task;
    final hasNewTask = eventTask != null && eventTask != current.task;
    final clearTask = nextState == 'IDLE' && eventTask == null;

    _machines[index] = MachineSnapshot(
      name: current.name,
      state: nextState,
      task: clearTask ? null : (eventTask ?? current.task),
      taskState: clearTask || hasNewTask ? null : current.taskState,
      attempt: clearTask || hasNewTask ? null : current.attempt,
      lastMessage: event.message ?? current.lastMessage,
      logs: current.logs,
    );
  }

  void _applyTaskState(RunEvent event) {
    final index = _machineIndex(event.machine);
    final task = event.task;
    if (index == -1 || task == null) return;
    final current = _machines[index];
    _machines[index] = MachineSnapshot(
      name: current.name,
      state: current.state,
      task: task,
      taskState: event.state?.toUpperCase() ?? current.taskState,
      attempt: event.attempt ?? current.attempt,
      lastMessage: event.message ?? current.lastMessage,
      logs: current.logs,
    );
  }

  void _applyLog(RunEvent event) {
    final entry = MachineLogEntry(
      seq: event.seq,
      timestamp: event.timestamp,
      message: event.message ?? '',
      machine: event.machine,
      task: event.task,
    );
    final index = _machineIndex(event.machine);
    if (index == -1) {
      _generalLogs.add(entry);
      if (_generalLogs.length > maxLogsPerMachine) {
        _generalLogs.removeRange(0, _generalLogs.length - maxLogsPerMachine);
      }
      return;
    }

    final current = _machines[index];
    final logs = <MachineLogEntry>[...current.logs, entry];
    final start = logs.length > maxLogsPerMachine
        ? logs.length - maxLogsPerMachine
        : 0;
    _machines[index] = MachineSnapshot(
      name: current.name,
      state: current.state,
      task: current.task,
      taskState: current.taskState,
      attempt: current.attempt,
      lastMessage: current.lastMessage,
      logs: logs.sublist(start),
    );
  }

  static int _machineIndex(String? machine) {
    if (machine == null) return -1;
    final match = RegExp(r'^cpu([1-6])$').firstMatch(machine);
    return match == null ? -1 : int.parse(match.group(1)!) - 1;
  }
}
