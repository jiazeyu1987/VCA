# -*- coding: utf-8 -*-
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
from PIL import Image


SCHEMA_VERSION = "1.0"
STOP_SENTINEL = object()


@dataclass(frozen=True)
class SessionRecorderConfig:
    enabled: bool
    output_dir: Optional[str] = None
    frame_format: str = "png"
    max_writer_queue: int = 256
    include_online_response: bool = True
    include_trace_json: bool = True
    package_on_finish: bool = True

    def sanitized(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "output_dir": self.output_dir,
            "frame_format": self.frame_format,
            "max_writer_queue": int(self.max_writer_queue),
            "include_online_response": bool(self.include_online_response),
            "include_trace_json": bool(self.include_trace_json),
            "package_on_finish": bool(self.package_on_finish),
        }


@dataclass
class RecordingSession:
    session_id: str
    point_id: object
    partial_dir: Path
    package_path: Path
    meta: dict
    server: dict
    recording_config: dict
    created_at_iso: str
    offline_start_epoch_ms: int
    offline_start_perf_counter_ns: int
    write_queue: queue.Queue
    writer_thread: threading.Thread
    events: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "active"
    frame_count: int = 0
    online_event_count: int = 0
    result_count: int = 0
    offline_stop_requested_epoch_ms: Optional[int] = None
    offline_stop_requested_perf_counter_ns: Optional[int] = None
    offline_end_epoch_ms: Optional[int] = None
    offline_end_perf_counter_ns: Optional[int] = None
    completed_package_path: Optional[Path] = None
    failure: Optional[BaseException] = None


def parse_session_recorder_config(settings: dict) -> SessionRecorderConfig:
    if not isinstance(settings, dict):
        raise ValueError("settings must be a JSON object")
    if "session_recording" not in settings:
        raise ValueError("settings.session_recording is required")
    raw = settings.get("session_recording")
    if not isinstance(raw, dict):
        raise ValueError("settings.session_recording must be an object")

    enabled = _required_bool(raw, "enabled")
    if not enabled:
        return SessionRecorderConfig(enabled=False, include_online_response=False, include_trace_json=False, package_on_finish=False)

    output_dir = raw.get("output_dir")
    if output_dir is None or str(output_dir).strip() == "":
        raise ValueError("settings.session_recording.output_dir is required")
    frame_format = str(raw.get("frame_format", "")).strip().lower()
    if frame_format != "png":
        raise ValueError("settings.session_recording.frame_format must be png")
    try:
        max_writer_queue = int(raw.get("max_writer_queue"))
    except Exception as exc:
        raise ValueError("settings.session_recording.max_writer_queue must be an integer > 0") from exc
    if max_writer_queue <= 0:
        raise ValueError("settings.session_recording.max_writer_queue must be an integer > 0")

    include_online_response = _required_bool(raw, "include_online_response")
    include_trace_json = _required_bool(raw, "include_trace_json")
    package_on_finish = _required_bool(raw, "package_on_finish")
    if not package_on_finish:
        raise ValueError("settings.session_recording.package_on_finish must be true")

    return SessionRecorderConfig(
        enabled=True,
        output_dir=str(output_dir),
        frame_format=frame_format,
        max_writer_queue=max_writer_queue,
        include_online_response=include_online_response,
        include_trace_json=include_trace_json,
        package_on_finish=package_on_finish,
    )


def write_png(path: Path, image: np.ndarray) -> None:
    arr = np.asarray(image)
    if arr.ndim == 2:
        pil_image = Image.fromarray(arr.astype(np.uint8))
    elif arr.ndim == 3 and arr.shape[2] == 1:
        pil_image = Image.fromarray(arr[:, :, 0].astype(np.uint8))
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        pil_image = Image.fromarray(arr.astype(np.uint8))
    else:
        raise ValueError(f"unsupported image shape for session recording png: {arr.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    pil_image.save(path, format="PNG")


class SessionDataRecorder:
    def __init__(
        self,
        config: SessionRecorderConfig,
        logger: Optional[logging.Logger] = None,
        id_factory: Optional[Callable[[object], str]] = None,
    ):
        self._config = config
        self._logger = logger or logging.getLogger("pywrapper_api_server")
        self._id_factory = id_factory or default_session_id
        self._lock = threading.Lock()
        self._active_session: Optional[RecordingSession] = None
        self._last_completed_package_path: Optional[Path] = None
        self._last_failure: Optional[BaseException] = None
        self._logger.info(
            "SESSION_RECORDING config_loaded: %s",
            json.dumps(self._config.sanitized(), ensure_ascii=False, sort_keys=True),
        )

    @property
    def config(self) -> SessionRecorderConfig:
        return self._config

    def is_active(self) -> bool:
        with self._lock:
            session = self._active_session
            return bool(self._config.enabled and session is not None and session.state in {"active", "stopping"})

    def start_session(self, point_id, meta: Optional[dict] = None, server: Optional[dict] = None) -> Optional[str]:
        if not self._config.enabled:
            return None
        with self._lock:
            if self._active_session is not None and self._active_session.state in {"active", "stopping", "finalizing"}:
                raise RuntimeError("session recording already active")
            session_id = self._id_factory(point_id)
            output_dir = Path(str(self._config.output_dir))
            output_dir.mkdir(parents=True, exist_ok=True)
            package_stem = f"session_{session_id}"
            partial_dir = output_dir / f"{package_stem}.partial"
            if partial_dir.exists():
                raise RuntimeError(f"session recording partial directory already exists: {partial_dir}")
            partial_dir.mkdir(parents=True)
            (partial_dir / "frames").mkdir()
            (partial_dir / "results").mkdir()
            write_queue: queue.Queue = queue.Queue(maxsize=int(self._config.max_writer_queue))
            placeholder_thread = threading.Thread(target=lambda: None)
            now_epoch_ms, now_perf_counter_ns, now_iso = current_time_fields()
            session = RecordingSession(
                session_id=session_id,
                point_id=point_id,
                partial_dir=partial_dir,
                package_path=output_dir / f"{package_stem}.zip",
                meta=dict(meta or {}),
                server=dict(server or {}),
                recording_config=self._config.sanitized(),
                created_at_iso=now_iso,
                offline_start_epoch_ms=now_epoch_ms,
                offline_start_perf_counter_ns=now_perf_counter_ns,
                write_queue=write_queue,
                writer_thread=placeholder_thread,
            )
            session.writer_thread = threading.Thread(
                target=self._writer_loop,
                args=(session,),
                daemon=True,
                name=f"session-recorder-{session_id}",
            )
            session.writer_thread.start()
            self._active_session = session
            self._last_failure = None

        self._append_event(
            session,
            "offline_start",
            point_id=point_id,
            meta=dict(meta or {}),
            server=dict(server or {}),
        )
        self._logger.info(
            "SESSION_RECORDING session_started: session_id=%s point_id=%s partial_dir=%s",
            session.session_id,
            point_id,
            session.partial_dir,
        )
        return session.session_id

    def mark_offline_stop_requested(self, **fields) -> None:
        session = self._require_active_session()
        self._raise_if_failed(session)
        session.state = "stopping"
        epoch_ms, perf_counter_ns, _ = current_time_fields()
        session.offline_stop_requested_epoch_ms = epoch_ms
        session.offline_stop_requested_perf_counter_ns = perf_counter_ns
        self._append_event(session, "offline_stop_requested", **fields)
        self._logger.info(
            "SESSION_RECORDING stop_requested: session_id=%s point_id=%s",
            session.session_id,
            session.point_id,
        )

    def record_frame(
        self,
        image: np.ndarray,
        frame_seq: int,
        frame_ts: float,
        frame_index: int,
        source: str,
        tag: str,
        metrics: Optional[dict] = None,
    ) -> None:
        session = self._require_active_session()
        self._raise_if_failed(session)
        image_copy = np.array(image, copy=True)
        with session.lock:
            session.frame_count += 1
            frame_number = session.frame_count
        frame_id = f"frame_{frame_number:06d}"
        source_text = str(source)
        relative_path = f"frames/{frame_id}_seq_{int(frame_seq):09d}_{safe_name_part(source_text)}.png"
        output_path = session.partial_dir / relative_path
        shape = [int(v) for v in image_copy.shape]
        event_fields = {
            "frame_id": frame_id,
            "frame_seq": int(frame_seq),
            "frame_index": int(frame_index),
            "frame_ts_epoch_ms": int(round(float(frame_ts) * 1000.0)),
            "source": source_text,
            "tag": str(tag),
            "path": relative_path,
            "shape": shape,
        }
        if metrics:
            event_fields.update(json_safe(metrics))

        def op() -> None:
            write_png(output_path, image_copy)
            self._append_event(session, "offline_frame", **event_fields)
            self._logger.info(
                "SESSION_RECORDING frame_recorded: session_id=%s point_id=%s frame_seq=%s path=%s",
                session.session_id,
                session.point_id,
                int(frame_seq),
                relative_path,
            )

        self._enqueue(session, op)

    def record_online_request(
        self,
        trace_id: Optional[str],
        request_started_perf_counter_ns: int,
        request_ended_perf_counter_ns: int,
        response_kind: str,
        response_summary: Optional[dict],
        latest_frame_seq: Optional[int] = None,
    ) -> None:
        session = self._optional_active_session()
        if session is None:
            return
        self._raise_if_failed(session)
        started_ns = int(request_started_perf_counter_ns)
        ended_ns = int(request_ended_perf_counter_ns)
        duration_ms = max(0.0, round(float(ended_ns - started_ns) / 1_000_000.0, 3))
        result_path = None
        result_payload = json_safe(dict(response_summary or {}))
        with session.lock:
            session.online_event_count += 1
            index = session.online_event_count
            if self._config.include_online_response:
                session.result_count += 1
                result_path = f"results/online_{index:06d}.json"
        event_fields = {
            "trace_id": trace_id,
            "request_started_perf_counter_ns": started_ns,
            "request_ended_perf_counter_ns": ended_ns,
            "server_duration_ms": duration_ms,
            "response_kind": str(response_kind),
            "latest_frame_seq": int(latest_frame_seq) if latest_frame_seq is not None else None,
            "result_path": result_path,
        }

        def op() -> None:
            if result_path is not None:
                write_json(session.partial_dir / result_path, result_payload)
            self._append_event(session, "online_request", **event_fields)
            self._logger.info(
                "SESSION_RECORDING online_recorded: session_id=%s trace_id=%s duration_ms=%s",
                session.session_id,
                trace_id,
                duration_ms,
            )

        self._enqueue(session, op)

    def record_offline_result(self, result_summary: dict) -> None:
        session = self._require_active_or_stopping_session()
        self._raise_if_failed(session)
        result_payload = json_safe(dict(result_summary or {}))
        with session.lock:
            session.result_count += 1
        result_path = "results/offline_result.json"

        def op() -> None:
            write_json(session.partial_dir / result_path, result_payload)
            self._append_event(
                session,
                "offline_result",
                result_path=result_path,
                response_success=result_payload.get("success"),
                response_info=result_payload.get("info"),
            )

        self._enqueue(session, op)

    def finish_session(self) -> Optional[Path]:
        if not self._config.enabled:
            return None
        with self._lock:
            session = self._active_session
            if session is None:
                if self._last_completed_package_path is not None:
                    return self._last_completed_package_path
                if self._last_failure is not None:
                    raise self._last_failure
                raise RuntimeError("no active session recording to finish")
            if session.state == "completed" and session.completed_package_path is not None:
                return session.completed_package_path
            session.state = "finalizing"

        package_finalize_start_ns = time.perf_counter_ns()
        try:
            session.write_queue.join()
            self._raise_if_failed(session)
            self._stop_writer(session)

            epoch_ms, perf_counter_ns, _ = current_time_fields()
            session.offline_end_epoch_ms = epoch_ms
            session.offline_end_perf_counter_ns = perf_counter_ns
            self._append_event(session, "offline_end", point_id=session.point_id)
            package_finalize_end_ns = time.perf_counter_ns()
            self._append_event(
                session,
                "package_finalized",
                package_path=str(session.package_path),
                package_finalize_duration_ms=round(float(package_finalize_end_ns - package_finalize_start_ns) / 1_000_000.0, 3),
            )

            if self._config.include_trace_json:
                write_json(
                    session.partial_dir / "trace.json",
                    {"traceEvents": self._build_trace_events(session, package_finalize_start_ns, package_finalize_end_ns)},
                )
            self._write_manifest(session)
            self._write_checksums(session)
            self._write_zip_package(session)

            session.state = "completed"
            session.completed_package_path = session.package_path
            with self._lock:
                self._last_completed_package_path = session.package_path
                self._active_session = None
            shutil.rmtree(session.partial_dir)
            self._logger.info(
                "SESSION_RECORDING package_finalized: session_id=%s point_id=%s package_path=%s frame_count=%s online_event_count=%s",
                session.session_id,
                session.point_id,
                session.package_path,
                session.frame_count,
                session.online_event_count,
            )
            return session.package_path
        except BaseException as exc:
            self._set_failure(session, exc)
            self._stop_writer(session)
            session.state = "failed"
            with self._lock:
                self._active_session = None
                self._last_failure = exc
            self._logger.exception(
                "SESSION_RECORDING failed: session_id=%s point_id=%s error=%s",
                session.session_id,
                session.point_id,
                exc,
            )
            raise

    def _optional_active_session(self) -> Optional[RecordingSession]:
        if not self._config.enabled:
            return None
        with self._lock:
            session = self._active_session
        if session is None or session.state not in {"active", "stopping"}:
            return None
        return session

    def _require_active_session(self) -> RecordingSession:
        session = self._optional_active_session()
        if session is None:
            raise RuntimeError("no active session recording")
        return session

    def _require_active_or_stopping_session(self) -> RecordingSession:
        session = self._optional_active_session()
        if session is None:
            with self._lock:
                session = self._active_session
            if session is None or session.state != "finalizing":
                raise RuntimeError("no active session recording")
        return session

    def _enqueue(self, session: RecordingSession, op: Callable[[], None]) -> None:
        self._raise_if_failed(session)
        try:
            session.write_queue.put_nowait(op)
        except queue.Full as exc:
            failure = RuntimeError("session recording writer queue is full")
            self._set_failure(session, failure)
            raise failure from exc

    def _writer_loop(self, session: RecordingSession) -> None:
        while True:
            item = session.write_queue.get()
            try:
                if item is STOP_SENTINEL:
                    return
                item()
            except BaseException as exc:
                self._set_failure(session, exc)
                self._logger.exception(
                    "SESSION_RECORDING failed: session_id=%s point_id=%s error=%s",
                    session.session_id,
                    session.point_id,
                    exc,
                )
            finally:
                session.write_queue.task_done()

    def _stop_writer(self, session: RecordingSession) -> None:
        if not session.writer_thread.is_alive():
            return
        try:
            session.write_queue.put(STOP_SENTINEL, timeout=1.0)
        except Exception:
            pass
        session.writer_thread.join(timeout=5.0)

    def _set_failure(self, session: RecordingSession, exc: BaseException) -> None:
        with session.lock:
            if session.failure is None:
                session.failure = exc

    def _raise_if_failed(self, session: RecordingSession) -> None:
        with session.lock:
            failure = session.failure
        if failure is not None:
            raise failure

    def _append_event(self, session: RecordingSession, event_type: str, **fields) -> None:
        epoch_ms, perf_counter_ns, wall_time_iso = current_time_fields()
        event = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session.session_id,
            "event_type": event_type,
            "wall_time_iso": wall_time_iso,
            "epoch_ms": epoch_ms,
            "perf_counter_ns": perf_counter_ns,
        }
        event.update(json_safe(fields))
        with session.lock:
            with open(session.partial_dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=json_default))
                f.write("\n")
            session.events.append(event)

    def _write_manifest(self, session: RecordingSession) -> None:
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session.session_id,
            "point_id": session.point_id,
            "created_at_iso": session.created_at_iso,
            "offline_start_epoch_ms": session.offline_start_epoch_ms,
            "offline_stop_requested_epoch_ms": session.offline_stop_requested_epoch_ms,
            "offline_end_epoch_ms": session.offline_end_epoch_ms,
            "frame_count": int(session.frame_count),
            "online_event_count": int(session.online_event_count),
            "result_count": int(session.result_count),
            "server": json_safe(session.server),
            "recording_config": session.recording_config,
            "package_status": "completed",
            "meta": json_safe(session.meta),
        }
        write_json(session.partial_dir / "manifest.json", manifest)

    def _write_checksums(self, session: RecordingSession) -> None:
        checksums = {}
        for path in sorted(session.partial_dir.rglob("*")):
            if not path.is_file() or path.name == "checksums.json":
                continue
            relative = path.relative_to(session.partial_dir).as_posix()
            checksums[relative] = sha256_file(path)
        write_json(session.partial_dir / "checksums.json", checksums)

    def _write_zip_package(self, session: RecordingSession) -> None:
        tmp_zip_path = Path(str(session.package_path) + ".tmp")
        if tmp_zip_path.exists():
            tmp_zip_path.unlink()
        with zipfile.ZipFile(tmp_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(session.partial_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(session.partial_dir).as_posix())
        with zipfile.ZipFile(tmp_zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"session recording zip integrity check failed: {bad_member}")
        os.replace(str(tmp_zip_path), str(session.package_path))

    def _build_trace_events(
        self,
        session: RecordingSession,
        package_finalize_start_ns: int,
        package_finalize_end_ns: int,
    ) -> list:
        events = list(session.events)
        trace_events = []
        start_event = first_event(events, "offline_start")
        stop_event = first_event(events, "offline_stop_requested")
        end_event = first_event(events, "offline_end")
        if start_event is not None and end_event is not None:
            trace_events.append(duration_trace_event("offline_session", "algorithm", start_event, end_event, tid=1))
        if start_event is not None and stop_event is not None:
            trace_events.append(duration_trace_event("offline_capture", "algorithm", start_event, stop_event, tid=1))
        for event in events:
            if event.get("event_type") == "offline_frame":
                trace_events.append(
                    {
                        "name": "offline_frame",
                        "cat": "frame",
                        "ph": "i",
                        "s": "t",
                        "ts": int(event["perf_counter_ns"] // 1000),
                        "pid": 1,
                        "tid": 2,
                        "args": {
                            "frame_id": event.get("frame_id"),
                            "frame_seq": event.get("frame_seq"),
                            "path": event.get("path"),
                        },
                    }
                )
            elif event.get("event_type") == "online_request":
                started_ns = int(event.get("request_started_perf_counter_ns") or event["perf_counter_ns"])
                ended_ns = int(event.get("request_ended_perf_counter_ns") or started_ns)
                trace_events.append(
                    {
                        "name": "online_request",
                        "cat": "algorithm",
                        "ph": "X",
                        "ts": int(started_ns // 1000),
                        "dur": max(0, int((ended_ns - started_ns) // 1000)),
                        "pid": 1,
                        "tid": 3,
                        "args": {
                            "trace_id": event.get("trace_id"),
                            "response_kind": event.get("response_kind"),
                            "latest_frame_seq": event.get("latest_frame_seq"),
                        },
                    }
                )
        trace_events.append(
            {
                "name": "package_finalize",
                "cat": "recording",
                "ph": "X",
                "ts": int(package_finalize_start_ns // 1000),
                "dur": max(0, int((package_finalize_end_ns - package_finalize_start_ns) // 1000)),
                "pid": 1,
                "tid": 4,
                "args": {"package_path": str(session.package_path)},
            }
        )
        return trace_events


def _required_bool(raw: dict, key: str) -> bool:
    if key not in raw or not isinstance(raw.get(key), bool):
        raise ValueError(f"settings.session_recording.{key} is required and must be boolean")
    return bool(raw[key])


def current_time_fields() -> tuple[int, int, str]:
    return (
        int(round(time.time() * 1000.0)),
        time.perf_counter_ns(),
        datetime.now().isoformat(timespec="milliseconds"),
    )


def default_session_id(point_id) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return f"{timestamp}_point_{safe_name_part(point_id)}_{uuid.uuid4().hex[:8]}"


def safe_name_part(value) -> str:
    text = str(value)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text or "unknown"


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True, default=json_default),
        encoding="utf-8",
    )


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return str(value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def first_event(events: list, event_type: str) -> Optional[dict]:
    for event in events:
        if event.get("event_type") == event_type:
            return event
    return None


def duration_trace_event(name: str, category: str, start_event: dict, end_event: dict, tid: int) -> dict:
    start_ns = int(start_event["perf_counter_ns"])
    end_ns = int(end_event["perf_counter_ns"])
    return {
        "name": name,
        "cat": category,
        "ph": "X",
        "ts": int(start_ns // 1000),
        "dur": max(0, int((end_ns - start_ns) // 1000)),
        "pid": 1,
        "tid": int(tid),
        "args": {},
    }
