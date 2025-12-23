from enum import Enum

# all different protocol codes

class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"

class ActorKind(str, Enum):
    CONTROLLER = "controller"
    HUB = "hub"
    SLOT = "slot"

class Command(str, Enum):
    RUN_TASK = "run_task"
    STOP_TASK = "stop_task"
    SET_ATTRIBUTES = "set_attributes"
    GET_SCREENSHOT = "get_screenshot"
    GET_SLOT_STATE = "get_slot_state"
    GET_SLOTS = "get_slots"
    UPLOAD_PLUGIN = "upload_plugin"
    GET_PLUGINS = "get_plugins"

class EventType(str, Enum):
    HEARTBEAT = "heartbeat"
    SLOT_STATE_CHANGED = "slot_state_changed"
    TASK_STATE_CHANGED = "task_state_changed"
    TASK_LOG = "task_log"
    SCREENSHOT_READY = "screenshot_ready"
    PLUGIN_INSTALLED = "plugin_installed"
    PLUGIN_INSTALL_FAILED = "plugin_install_failed"
    SLOT_ERROR = "slot_error"

class TargetKind(str, Enum):
    SLOT = "slot"
    SLOTS = "slots"
    ALL_SLOTS = "all_slots"
    FILTER = "filter"

class SlotStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"

class SlotHealth(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"

class TaskState(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

class TaskStopReason(str, Enum):
    REQUESTED = "requested"
    ERROR = "error"
    TIMEOUT = "timeout"
    SLOT_SHUTDOWN = "slot_shutdown"
    PREEMPTED = "preempted"

class PluginInstallState(str, Enum):
    INSTALLING = "installing"
    INSTALLED = "installed"
    FAILED = "failed"

class PluginScope(str, Enum):
    NODE = "node"
    SLOT = "slot"

class ErrorCode(str, Enum):
    BAD_REQUEST = "BAD_REQUEST"
    UNSUPPORTED_PROTOCOL_VERSION = "UNSUPPORTED_PROTOCOL_VERSION"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    UNAUTHORISED = "UNAUTHORISED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

class SlotErrorCode(str, Enum):
    SLOT_BUSY = "SLOT_BUSY"
    SLOT_OFFLINE = "SLOT_OFFLINE"
    SLOT_NOT_FOUND = "SLOT_NOT_FOUND"

class TaskErrorCode(str, Enum):
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_NOT_STOPPABLE = "TASK_NOT_STOPPABLE"
    TASK_FAILED = "TASK_FAILED"

class PluginErrorCode(str, Enum):
    PLUGIN_NOT_FOUND = "PLUGIN_NOT_FOUND"
    PLUGIN_INVALID = "PLUGIN_INVALID"
    PLUGIN_INSTALL_FAILED = "PLUGIN_INSTALL_FAILED"

{
  "v": 1,
  "type": "request",
  "id": "01JFM4R9QK8Z3Y3Y4Q8C2Z7N0M",
  "ts": "2025-12-21T16:20:00Z",

  "src": { "kind": "controller", "id": "ctl-01" },
  "dst": { "kind": "hub", "id": "node-01" },

  "cmd": "run_task",
  "target": { "kind": "slots", "ids": ["slot-01", "slot-02"] },

  "payload": {}
}

{
  "v": 1,
  "type": "response",
  "id": "01JFM4R9QK8Z3Y3Y4Q8C2Z7N0M",
  "in_reply_to": "01JFM4R9QK8Z3Y3Y4Q8C2Z7N0M",
  "src": { "kind": "hub", "id": "node-01" },
  "dst": { "kind": "controller", "id": "ctl-01" },
  "cmd": "run_task",
  "ok": True,
  "result": {
    "accepted": ["slot-01"],
    "rejected": [
      { "slot_id": "slot-02", "code": "SLOT_BUSY" }
    ]
  }
}

{
  "v": 1,
  "type": "event",
  "id": "01JFM4S1D2R7TQ2B5K9J6A3P0C",
  "ts": "2025-12-21T16:20:05Z",
  "src": { "kind": "slot", "id": "slot-01" },
  "dst": { "kind": "hub", "id": "node-01" },
  "event": "task_state_changed",
  "payload": {
    "task_id": "task-9c1d",
    "state": "running"
  }
}