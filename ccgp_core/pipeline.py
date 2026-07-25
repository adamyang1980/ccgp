from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from ccgp_core.antibot import ChallengeStateMachine, RunContext


class ChallengeDetected(RuntimeError):
    def __init__(self, kind: str, message: str = "", evidence: Optional[Dict[str, Any]] = None):
        super().__init__(message or kind)
        self.kind = kind
        self.message = message or kind
        self.evidence = evidence or {}


def _lower_text(s: str) -> str:
    return (s or "").lower()


def detect_challenge_text(text: str) -> Optional[str]:
    t = _lower_text(text)
    if not t:
        return None
    for k in (
        "aliyun",
        "nc_1",
        "nc-container",
        "滑动验证",
        "滑块",
        "访问验证",
        "安全验证",
        "captcha",
        "recaptcha",
        "人机验证",
        "verify",
    ):
        if k in t:
            if "aliyun" in t or "nc_" in t or "滑块" in t or "滑动验证" in t:
                return "slider"
            if "captcha" in t or "recaptcha" in t:
                return "captcha"
            return "access_verify"
    return None


def detect_challenge_http(
    *,
    status_code: int,
    content_type: str,
    body_text: str,
    expect_json: bool,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    if status_code in (401, 403):
        return ("access_verify", {"status_code": status_code})
    if status_code in (429,):
        return ("access_verify", {"status_code": status_code})

    ct = _lower_text(content_type)
    if expect_json and "application/json" not in ct:
        kind = detect_challenge_text(body_text) or "access_verify"
        return (kind, {"content_type": content_type})

    kind = detect_challenge_text(body_text)
    if kind:
        return (kind, {"content_type": content_type})
    return None


@dataclass
class ProbeResult:
    kind: str
    engine: str
    evidence: Dict[str, Any]


def probe_with_http_request(
    *,
    request_fn: Callable[[], Tuple[int, str, str]],
    expect_json: bool,
) -> ProbeResult:
    status_code, content_type, body_text = request_fn()
    detected = detect_challenge_http(
        status_code=status_code,
        content_type=content_type,
        body_text=body_text,
        expect_json=expect_json,
    )
    if detected:
        kind, evidence = detected
        engine = "BROWSER" if kind in ("slider", "access_verify") else "HTTP"
        return ProbeResult(kind=kind, engine=engine, evidence=evidence)
    return ProbeResult(kind="none", engine="HTTP", evidence={})


def run_phase_with_probe_and_fallback(
    *,
    phase: str,
    ctx: RunContext,
    sm: ChallengeStateMachine,
    probe: Callable[[], ProbeResult],
    run_http: Callable[[], Any],
    run_browser: Optional[Callable[[], Any]] = None,
    max_switches: int = 2,
    interactive_wait_seconds: int = 60,
) -> Any:
    switches = 0
    last_probe: Optional[ProbeResult] = None

    while True:
        pr = probe()
        last_probe = pr
        ctx.incr_stat(f"{phase}_probe", 1)

        if pr.kind != "none":
            sm.detected(kind=pr.kind, message=f"{phase}_probe", evidence=pr.evidence)

        engine = pr.engine
        if engine == "BROWSER" and run_browser is None:
            sm.manual_required(
                kind=pr.kind,
                message=f"{phase} requires browser but browser runner not configured",
                wait_seconds=interactive_wait_seconds,
                extra={"phase": phase, "evidence": pr.evidence},
            )
            if ctx.wait_for_manual():
                switches += 1
                if switches > max_switches:
                    raise ChallengeDetected(pr.kind, f"{phase} exceeded manual retries", pr.evidence)
                continue
            raise ChallengeDetected(pr.kind, f"{phase} manual required", pr.evidence)

        try:
            if engine == "HTTP":
                return run_http()
            return run_browser()
        except ChallengeDetected as cd:
            ctx.incr_stat(f"{phase}_challenge_detected", 1)
            sm.detected(kind=cd.kind, message=f"{phase}_run", evidence=cd.evidence)
            switches += 1
            if switches > max_switches:
                raise
            continue
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            kind = detect_challenge_text(msg) or (last_probe.kind if last_probe else "unknown")
            switches += 1
            if switches <= max_switches and kind in ("slider", "access_verify", "captcha", "unknown"):
                sm.detected(kind=kind, message=f"{phase}_exception", evidence={"error": msg})
                continue
            raise

