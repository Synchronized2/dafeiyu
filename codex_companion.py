"""Drive the upstream BigFish window from local Codex rollout events.

This observer never calls a model, sends prompts, or writes to the Codex home.
Only known event types change state; a tool error is not a failed whole task.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import json
from heapq import nlargest
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any

from codex_platform import SingleInstance

ROOT = Path(__file__).resolve().parent
# Internal supervisor result; helper failures are always returned as positive codes.
RESTART_REQUESTED = -1
ACTIVE = {"THINKING", "WORKING", "WAITING"}
PRIORITY = {"WAITING": 4, "WORKING": 3, "THINKING": 2, "ERROR": 1}
QUESTION_TOOLS = {"request_user_input", "request_user_input_async"}
TERMINAL_EVENTS = {
    "task_complete", "task_completed", "turn_completed",
    "turn_aborted", "task_aborted", "task_cancelled", "task_failed", "turn_failed",
}


def message(kind: str, **fields: Any) -> dict[str, Any]:
    return {"protocolVersion": 1, "kind": kind, "timestamp": int(time.time() * 1000), **fields}


def event_time(value: Any) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def activity_for(name: str, arguments: Any) -> tuple[str, str]:
    # Examine tool names and commands to select an animation, never show them.
    text = (name + " " + (arguments if isinstance(arguments, str) else json.dumps(arguments))).lower()
    if any(word in text for word in ("apply_patch", "write_file", "edit_file")):
        return "editing", "正在修改文件"
    if re.search(r"\b(pytest|unittest|cargo test|npm test|npm run test|lint)\b", text):
        return "testing", "正在检查结果"
    if any(word in name.lower() for word in ("search", "fetch", "read", "browse", "view_image")):
        return "searching", "正在查找资料"
    if re.search(r"\b(rg|cat|sed|curl|find|ls)\b", text):
        return "searching", "正在查找资料"
    if any(word in text for word in ("exec_command", "shell", "terminal", "write_stdin")):
        return "commanding", "正在执行任务"
    return "using-tool", "正在使用工具"


def tool_state(name: str, arguments: Any) -> tuple[str, str, str]:
    if name.rsplit(".", 1)[-1] in QUESTION_TOOLS:
        return "WAITING", "", "有件事需要你确认"
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    if re.search(r'''["']?sandbox_permissions["']?\s*:\s*["']require_escalated["']''', raw):
        return "WAITING", "", "正在请求操作授权"
    activity, text = activity_for(name, arguments)
    return "WORKING", activity, text


@dataclass
class Session:
    id: str
    project: str = "Codex"
    state: str = "IDLE"
    text: str = "我在这儿等新任务哦"
    activity: str = ""
    updated: float = 0
    turn_id: str = ""
    running: bool = False
    calls: OrderedDict[str, tuple[str, str, str]] = field(default_factory=OrderedDict)
    seen_items: set[str] = field(default_factory=set)
    task: str = ""
    progress: str = ""
    live_terminal: bool = False
    metadata_seen: bool = False
    is_subagent: bool = False

    def set_state(self, state: str, text: str, activity: str = "") -> None:
        self.state, self.text, self.activity = state, text, activity

    def after_tool(self) -> None:
        if self.calls:
            state, activity, text = next(reversed(self.calls.values()))
            self.set_state(state, text, activity)
        elif self.running:
            self.set_state("THINKING", "正在整理下一步")

    def apply(self, row: dict[str, Any]) -> bool:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            return False
        kind = row.get("type")
        typ = payload.get("type")
        stamp = event_time(row.get("timestamp"))
        if kind in {"session_meta", "turn_context"}:
            if kind == "session_meta" and self.metadata_seen:
                # Forked histories can contain the parent's metadata later in
                # the file. The recording's first metadata owns its identity.
                return False
            if payload.get("cwd"):
                self.project = Path(str(payload["cwd"])).name or "Codex"
            if kind == "session_meta":
                self.id = str(payload.get("id") or payload.get("session_id") or self.id)
                source = payload.get("source")
                self.is_subagent = source == "subagent" or isinstance(source, dict) and "subagent" in source
                self.metadata_seen = True
            return True
        if kind == "event_msg":
            # Delayed terminal events must not end a newer turn. Older rollout
            # formats without turn IDs retain their existing behaviour.
            if typ in TERMINAL_EVENTS:
                turn = str(payload.get("turn_id") or "")
                if turn and self.turn_id and turn != self.turn_id:
                    return False
            if typ in {"task_started", "turn_started"}:
                self.running = True
                self.turn_id = str(payload.get("turn_id", ""))
                self.calls.clear()
                self.seen_items.clear()
                self.task = self.progress = ""
                self.live_terminal = False
                self.set_state("THINKING", "收到，开始想办法啦")
            elif typ in {"task_complete", "task_completed", "turn_completed"}:
                self.running = False
                self.calls.clear()
                self.set_state("SUCCESS", "这一轮任务完成啦")
            elif typ in {"turn_aborted", "task_aborted", "task_cancelled"}:
                self.running = False
                self.calls.clear()
                self.set_state("IDLE", "已停下，等你下一句话")
            elif typ in {"task_failed", "turn_failed"}:
                self.running = False
                self.calls.clear()
                self.set_state("ERROR", "这一轮遇到问题了")
            elif typ == "approval_requested" or typ in QUESTION_TOOLS:
                self.set_state("WAITING", "有件事需要你确认")
            elif typ == "item_completed" and isinstance(payload.get("item"), dict):
                item = payload["item"]
                item_id = str(item.get("id", ""))
                if item_id and item_id in self.seen_items:
                    return False
                if item_id:
                    self.seen_items.add(item_id)
                item_type = str(item.get("type", "")).lower()
                if self.running and item_type == "commandexecution":
                    activity, text = activity_for("exec_command", str(item.get("command", "")))
                    self.set_state("WORKING", text, activity)
                elif self.running and item_type == "filechange":
                    self.set_state("WORKING", "正在修改文件", "editing")
                else:
                    return False
            else:
                return False
        elif kind == "response_item":
            if typ in {"function_call", "custom_tool_call"}:
                if not self.running:
                    return False
                name = str(payload.get("name", ""))
                args = payload.get("arguments", payload.get("input", ""))
                call_id = str(payload.get("call_id") or payload.get("id") or name)
                self.calls[call_id] = tool_state(name, args)
                if name.rsplit(".", 1)[-1] == "update_plan":
                    self.update_plan(args)
                self.after_tool()
            elif typ in {"function_call_output", "custom_tool_call_output"}:
                call_id = str(payload.get("call_id", ""))
                if call_id not in self.calls:
                    return False
                del self.calls[call_id]
                self.after_tool()
            elif typ == "reasoning" and self.running and not self.calls:
                self.set_state("THINKING", "正在认真想办法")
            elif typ == "message" and payload.get("role") == "assistant" and self.running and not self.calls:
                # A final message alone is not proof that the turn has ended.
                self.set_state("THINKING", "正在整理回答")
            else:
                return False
        else:
            return False
        self.updated = max(self.updated, stamp)
        return True

    def update_plan(self, arguments: Any) -> None:
        try:
            data = json.loads(arguments) if isinstance(arguments, str) else arguments
            steps = data.get("plan", [])
            if not steps:
                return
            completed = sum(step.get("status") == "completed" for step in steps)
            current = next((s for s in steps if s.get("status") == "in_progress"), {})
            self.task = " ".join(str(current.get("step", "")).split())[:70]
            self.progress = f"步骤 {completed}/{len(steps)}"
        except (ValueError, AttributeError, TypeError):
            return


@dataclass
class Tail:
    path: Path
    session: Session
    offset: int = 0
    identity: tuple[int, int] | None = None
    initial_size: int | None = None

    def read(self, budget: int = 2 * 1024 * 1024) -> bool:
        """Read complete UTF-8 JSONL records, including appends after a partial line."""
        changed = False
        try:
            stat = self.path.stat()
            identity = (stat.st_dev, stat.st_ino)
            if self.identity is not None and (identity != self.identity or stat.st_size < self.offset):
                self.offset = 0
                self.session = Session(self.path.stem)
                self.initial_size = None
                changed = True
            self.identity = identity
            if self.initial_size is None:
                self.initial_size = stat.st_size
            if stat.st_size == self.offset:
                return changed
            with self.path.open("rb") as stream:
                stream.seek(self.offset)
                data = stream.read(budget)
            end = data.rfind(b"\n")
            if end < 0:
                # Skip an oversized record in bounded chunks, never buffer it indefinitely.
                if len(data) == budget:
                    self.offset += len(data)
                return changed
            line_offset = self.offset
            self.offset += end + 1
            for line in data[:end].split(b"\n"):
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        applied = self.session.apply(row)
                        if applied and self.session.state in {"SUCCESS", "ERROR"}:
                            self.session.live_terminal = line_offset >= self.initial_size
                        changed = applied or changed
                except (ValueError, UnicodeError, TypeError):
                    continue
                finally:
                    line_offset += len(line) + 1
        except OSError:
            return changed
        return changed


class Observer:
    def __init__(self, home: Path, max_sessions: int = 24, thread: str | None = None) -> None:
        self.home = home
        self.max_sessions = max_sessions
        self.thread = thread
        self.tails: dict[Path, Tail] = {}
        self.signature = ""
        self.last_scan = 0.0
        self.initial = True

    def scan(self) -> None:
        root = self.home / "sessions"
        try:
            # An old chat can be active today, so order by mtime rather than date folder.
            candidates = nlargest(self.max_sessions,
                                 (p for p in root.glob("*/*/*/*.jsonl") if not self.thread or self.thread in p.name),
                                 key=lambda p: p.stat().st_mtime)
            selected = set(candidates)
            self.tails = {p: t for p, t in self.tails.items() if p in selected}
            for path in candidates:
                self.tails.setdefault(path, Tail(path, Session(path.stem)))
        except OSError:
            pass

    def poll(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        if now - self.last_scan > 2:
            self.scan()
            self.last_scan = now
        for tail in self.tails.values():
            tail.read()
        # Finish the startup replay before showing a session's state.
        sessions = [tail.session for tail in self.tails.values()
                    if tail.initial_size is not None and tail.offset >= tail.initial_size
                    and (not tail.session.is_subagent or self.thread)]
        # A resumed chat may have several rollout recordings. Select its newest
        # state before counting work, so an old active copy cannot outlive a
        # completed recording of the same chat.
        latest_by_id: dict[str, Session] = {}
        for session in sessions:
            previous = latest_by_id.get(session.id)
            if previous is None or (session.updated, not session.running) > (previous.updated, not previous.running):
                latest_by_id[session.id] = session
        sessions = list(latest_by_id.values())
        active = [s for s in sessions if s.running and now - s.updated < 600]
        active.sort(key=lambda s: (PRIORITY.get(s.state, 0), s.updated), reverse=True)
        latest = max(sessions, key=lambda s: s.updated, default=None)
        selected = active[0] if active else latest
        if not selected or not (self.home / "sessions").is_dir():
            state, text, detail, activity = "IDLE", "我在这儿陪你哦", "可直接玩动作；Codex 开始任务后自动跟随", ""
        elif selected.running and now - selected.updated >= 600:
            state, text, detail, activity = "DISCONNECTED", "等待 Codex 更新状态", f"{selected.project} · 暂无新记录", ""
        elif selected.state in {"SUCCESS", "ERROR"} and (not selected.live_terminal or now - selected.updated > 10):
            state, text, detail, activity = "IDLE", "我在这儿等新任务哦", f"{selected.project} · Codex", ""
        else:
            state, text, activity = selected.state, selected.text, selected.activity
            parts = [selected.project, selected.progress, selected.task]
            detail = " · ".join(part for part in parts if part) or "Codex"
        tasks = [dict(sessionId=s.id, state=s.state, project=s.project, task=s.task, detail=s.progress) for s in active]
        fields = dict(state=state, message=text, detail=detail, activity=activity,
                      sessionId=selected.id if selected else "")
        signature = json.dumps([fields, tasks], sort_keys=True, ensure_ascii=False)
        self.initial = False
        if signature == self.signature:
            return []
        self.signature = signature
        # The upstream alert animation is a pulse with an idle underlay.
        if state in {"SUCCESS", "ERROR"}:
            fields.update(resumeState="IDLE", resumeMessage="我在这儿等新任务哦",
                          resumeDetail=f"{selected.project} · Codex", ttlMs=5000)
        return [message("pulse" if state in {"SUCCESS", "ERROR"} else "state", **fields), message("tasks", tasks=tasks)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex 大肥鱼：本地任务状态桌宠")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--thread", help="只跟随指定的聊天 ID，默认跟随本机最近的任务")
    parser.add_argument("--headless", action="store_true", help="输出状态，不显示窗口")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="演示动画，不读取 Codex 记录")
    modes.add_argument("--standalone", action="store_true", help="只当桌宠使用，不读取 Codex；右键可重新开启跟随")
    parser.add_argument("--duration", type=float, default=0, help="指定运行秒数，0 为持续运行")
    parser.add_argument("--snapshot", type=Path, help="保存窗口预览图")
    args = parser.parse_args()
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    lock = SingleInstance(local / "companion.lock")
    if not args.headless:
        if not lock.acquire():
            print("Codex 大肥鱼已经在运行了。", file=sys.stderr)
            return 0
    try:
        # Keep the single-instance lock while replacing the native window and observer.
        while True:
            code = run_companion(args, local)
            if code != RESTART_REQUESTED:
                return code
    finally:
        lock.close()


def run_companion(args: argparse.Namespace, local: Path) -> int:
    env = dict(os.environ)
    env.setdefault("DSH_DAFEIYU_LAYOUT_PATH", str(local / "layout.json"))
    env.setdefault("DSH_DAFEIYU_TITLE", "Codex 大肥鱼")
    env.setdefault("DSH_DAFEIYU_OPEN_LABEL", "打开 Codex")
    env.setdefault("DSH_DAFEIYU_WEBUI_URL", "codex://")
    env["DSH_DAFEIYU_STANDALONE"] = "1"
    # A status companion does not need balance queries or a model credential.
    # pythonw has no standard streams; use python.exe with a hidden console
    # for the JSONL child even when the launcher itself uses pythonw.
    helper_python = str(Path(sys.executable).with_name("python.exe")) if os.name == "nt" else sys.executable
    # The embedded Windows interpreter uses an explicit module search path;
    # launching as a package works on both platforms without adding runtime/
    # to global Python settings.
    cmd = [helper_python, "-m", "runtime.helper"]
    if args.headless:
        cmd.append("--headless")
    if args.snapshot:
        cmd.extend(["--snapshot", str(args.snapshot.resolve())])
    log = (local / "helper.log").open("a", encoding="utf-8")
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=env,
                             encoding="utf-8", bufsize=1, cwd=ROOT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    stopping = threading.Event()
    restart_requested = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())
    ready = threading.Event()
    follow_codex = threading.Event()
    if not args.standalone:
        follow_codex.set()

    def receive() -> None:
        assert child.stdout is not None
        for line in child.stdout:
            try:
                data = json.loads(line)
                if data.get("kind") == "ready":
                    ready.set()
                elif data.get("kind") == "restart":
                    restart_requested.set()
                    stopping.set()
                elif data.get("kind") == "closed":
                    stopping.set()
                elif data.get("kind") == "follow-codex" and isinstance(data.get("enabled"), bool):
                    follow_codex.set() if data["enabled"] else follow_codex.clear()
            except ValueError:
                pass

    receiver = threading.Thread(target=receive, daemon=True)
    receiver.start()

    def send(data: dict[str, Any]) -> None:
        assert child.stdin is not None
        child.stdin.write(json.dumps(data, ensure_ascii=False) + "\n")
        child.stdin.flush()
        if args.headless and data["kind"] in {"state", "pulse"}:
            print(json.dumps(data, ensure_ascii=False), flush=True)

    started = time.monotonic()
    try:
        while not ready.wait(.1):
            if child.poll() is not None or stopping.is_set() or time.monotonic() - started > 30:
                print(f"桌宠窗口未能启动，请查看 {local / 'helper.log'}", file=sys.stderr)
                return 1
        send(message("hello", host="codex", message="BigFish connected to Codex"))
        send(message("config", openUrl="codex://", openLabel="打开 Codex", restartSupported=True))
        observer = None
        previous_mode = None
        demo = [
            ("IDLE", "演示 · 我在这儿陪你哦", ""),
            ("THINKING", "演示 · 正在认真想办法", ""),
            ("WORKING", "演示 · 正在查找资料", "searching"),
            ("WORKING", "演示 · 正在修改文件", "editing"),
            ("WORKING", "演示 · 正在检查结果", "testing"),
            ("WAITING", "演示 · 有件事需要你确认", ""),
            ("SUCCESS", "演示 · 任务完成啦", ""),
            ("ERROR", "演示 · 这一轮遇到问题了", ""),
        ]
        demo_index = -1
        while child.poll() is None and not stopping.is_set():
            elapsed = time.monotonic() - started
            if args.duration and elapsed >= args.duration:
                break
            if args.demo:
                index = int(elapsed / 4) % len(demo)
                if index != demo_index:
                    demo_index = index
                    state, text, activity = demo[index]
                    send(message("state", state=state, message=text, activity=activity, detail="Codex 大肥鱼 · 动画演示"))
            else:
                following = follow_codex.is_set()
                if following != previous_mode:
                    previous_mode = following
                    observer = Observer(args.codex_home, thread=args.thread) if following else None
                    send(message("config", followCodex=following))
                    if not following:
                        send(message("tasks", tasks=[]))
                        send(message("state", state="IDLE", message="我在这儿陪你哦",
                                     detail="独立陪伴 · 右键可开启跟随 Codex"))
                if observer is not None:
                    for data in observer.poll():
                        send(data)
            stopping.wait(.35)
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    finally:
        if child.poll() is None:
            try:
                send(message("shutdown"))
                child.stdin.close()
                child.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if child.stdin is not None and not child.stdin.closed:
            try:
                child.stdin.close()
            except BrokenPipeError:
                # A crashed helper can leave buffered data in the pipe.
                pass
        receiver.join(timeout=2)
        if child.stdout is not None:
            child.stdout.close()
        log.close()
    if child.returncode:
        print(f"桌宠窗口异常退出（退出码 {child.returncode}），请查看 {local / 'helper.log'}", file=sys.stderr)
        return child.returncode if child.returncode > 0 else 1
    if restart_requested.is_set():
        # Follow the mode selected in the menu, rather than the original CLI mode.
        args.standalone = not follow_codex.is_set()
        return RESTART_REQUESTED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
