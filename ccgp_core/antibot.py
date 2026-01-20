import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ccgp_core.output import build_results_dir, ensure_dir, write_json


def find_latest_results_dir(site: str, *, root_dir: str = "results") -> Optional[str]:
    site_key = (site or "").strip().lower() or "unknown"
    base = os.path.join(root_dir, site_key)
    try:
        entries = [os.path.join(base, n) for n in os.listdir(base)]
    except Exception:
        return None
    dirs = [p for p in entries if os.path.isdir(p)]
    if not dirs:
        return None
    dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return dirs[0]


def prepare_results_dir(site: str, *, resume: bool = False, root_dir: str = "results") -> str:
    if resume:
        latest = find_latest_results_dir(site, root_dir=root_dir)
        if latest:
            ensure_dir(latest)
            return latest
    out_dir = build_results_dir(site, root_dir=root_dir)
    ensure_dir(out_dir)
    return out_dir


def _read_json_if_exists(path: str) -> Optional[Any]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@dataclass
class ChallengeEvent:
    ts: float
    state: str
    kind: str
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunContext:
    site: str
    out_dir: str
    interactive: bool = True
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)

    @property
    def checkpoint_path(self) -> str:
        return os.path.join(self.out_dir, "checkpoint.json")

    @property
    def manual_action_path(self) -> str:
        return os.path.join(self.out_dir, "manual_action.json")

    @property
    def challenge_events_path(self) -> str:
        return os.path.join(self.out_dir, "challenge_events.json")

    def load_checkpoint(self) -> Dict[str, Any]:
        data = _read_json_if_exists(self.checkpoint_path)
        if isinstance(data, dict):
            self.checkpoint = data
        else:
            self.checkpoint = {}
        return self.checkpoint

    def save_checkpoint(self) -> None:
        write_json(self.checkpoint_path, self.checkpoint)

    def set_checkpoint(self, **fields: Any) -> None:
        for k, v in fields.items():
            self.checkpoint[k] = v

    def incr_stat(self, key: str, inc: int = 1) -> None:
        cur = self.stats.get(key)
        if isinstance(cur, int):
            self.stats[key] = cur + inc
        else:
            self.stats[key] = inc
        write_json(os.path.join(self.out_dir, "run_stats.json"), self.stats)

    def write_manual_action(
        self,
        *,
        action_type: str,
        url: str = "",
        message: str = "",
        wait_seconds: int = 60,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "site": self.site,
            "action_type": action_type,
            "url": url,
            "message": message,
            "wait_seconds": wait_seconds,
            "out_dir": self.out_dir,
            "ts": time.time(),
        }
        if isinstance(extra, dict):
            payload["extra"] = extra
        write_json(self.manual_action_path, payload)

    def wait_for_manual(self, *, prompt: str = "") -> bool:
        if not self.interactive:
            return False
        try:
            input(prompt or "请完成手动验证后按 Enter 继续...")
            return True
        except Exception:
            return False


class ChallengeStateMachine:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.state = "NORMAL"
        self.last_kind = ""
        self.events: list[ChallengeEvent] = []

    def _emit(self, state: str, kind: str, message: str = "", evidence: Optional[Dict[str, Any]] = None) -> None:
        ev = ChallengeEvent(ts=time.time(), state=state, kind=kind, message=message, evidence=evidence or {})
        self.events.append(ev)
        self.state = state
        self.last_kind = kind
        serializable = [e.__dict__ for e in self.events]
        write_json(self.ctx.challenge_events_path, serializable)

    def detected(self, *, kind: str, message: str = "", evidence: Optional[Dict[str, Any]] = None) -> None:
        self.ctx.incr_stat("challenge_detected", 1)
        self._emit("CHALLENGE_DETECTED", kind, message, evidence)

    def auto_solving(self, *, kind: str, message: str = "", evidence: Optional[Dict[str, Any]] = None) -> None:
        self._emit("AUTO_SOLVING", kind, message, evidence)

    def passed(self, *, kind: str, message: str = "", evidence: Optional[Dict[str, Any]] = None) -> None:
        self.ctx.incr_stat("challenge_passed", 1)
        self._emit("PASSED", kind, message, evidence)
        self.state = "NORMAL"

    def manual_required(
        self,
        *,
        kind: str,
        url: str = "",
        message: str = "",
        wait_seconds: int = 60,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.ctx.incr_stat("challenge_manual_required", 1)
        self.ctx.write_manual_action(
            action_type=f"captcha_{kind}",
            url=url,
            message=message,
            wait_seconds=wait_seconds,
            extra=extra,
        )
        self._emit("MANUAL_REQUIRED", kind, message, {"url": url, "wait_seconds": wait_seconds, **(extra or {})})

    def cooldown(self, *, kind: str, seconds: float, message: str = "") -> None:
        self.ctx.incr_stat("challenge_cooldown", 1)
        self._emit("COOLDOWN", kind, message, {"seconds": seconds})
        time.sleep(max(0.0, seconds))
        self.state = "NORMAL"

