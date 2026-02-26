"""Docling serve manager using Docker/Podman container."""

import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List, AsyncIterator
from utils.logging_config import get_logger

logger = get_logger(__name__)

CONTAINER_NAME = "docling-serve"
DOCLING_IMAGE = "quay.io/docling-project/docling-serve-cpu:v1.5.0"


class DoclingManager:
    """Manages docling-serve as a Docker/Podman container via compose."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._port = 5001
        self._host = "0.0.0.0"
        self._workers = int(os.getenv("DOCLING_WORKERS", "1"))
        self._running = False
        self._starting = False

        self._log_buffer: List[str] = []
        self._max_log_lines = 1000
        self._log_lock = threading.Lock()

        self._initialized = True

        # Docker runs Linux, so OCR engine is always easyocr
        os.environ.setdefault("DOCLING_OCR_ENGINE", "easyocr")

        if self._is_container_running():
            self._running = True
            self._add_log_entry(f"Detected running {CONTAINER_NAME} container")

    def cleanup(self):
        """Cleanup resources. Container persists across TUI sessions."""
        self._add_log_entry("TUI exiting - docling-serve container will continue running")

    def _get_compose_command(self) -> list[str]:
        """Get the compose command from ContainerManager's detected runtime."""
        try:
            from tui.managers.container_manager import ContainerManager
            cm = ContainerManager()
            return cm.runtime_info.compose_command.copy()
        except Exception:
            return ["docker", "compose"]

    def _get_compose_file(self) -> Path:
        """Get the compose file path from ContainerManager."""
        try:
            from tui.managers.container_manager import ContainerManager
            cm = ContainerManager()
            return cm.compose_file
        except Exception:
            return Path("docker-compose.yml")

    def _get_env_file(self) -> Optional[Path]:
        """Get the env file path."""
        try:
            from utils.paths import get_tui_env_file
            tui_env = get_tui_env_file()
            if tui_env.exists():
                return tui_env
        except Exception:
            pass
        env_path = Path(".env")
        return env_path if env_path.exists() else None

    def _build_compose_cmd(self, args: list[str]) -> list[str]:
        """Build a full compose command with env-file and compose-file flags."""
        cmd = self._get_compose_command()
        env_file = self._get_env_file()
        if env_file:
            cmd.extend(["--env-file", str(env_file)])
        cmd.extend(["-f", str(self._get_compose_file())])
        cmd.extend(args)
        return cmd

    def _get_env_for_subprocess(self) -> dict[str, str]:
        """Get environment variables for subprocess, loading from .env file."""
        env = dict(os.environ)
        try:
            from dotenv import load_dotenv
            env_file = self._get_env_file()
            if env_file:
                load_dotenv(dotenv_path=env_file, override=True)
                env.update(os.environ)
        except Exception:
            pass
        return env

    async def _run_compose(self, args: list[str]) -> Tuple[bool, str, str]:
        """Run a compose command and return (success, stdout, stderr)."""
        cmd = self._build_compose_cmd(args)
        self._add_log_entry(f"Running: {' '.join(cmd)}")
        try:
            env = self._get_env_for_subprocess()
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path.cwd(),
                env=env,
            )
            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode() if stdout else ""
            stderr_text = stderr.decode() if stderr else ""
            success = process.returncode == 0
            if not success:
                self._add_log_entry(f"Command failed: {stderr_text[:500]}")
            return success, stdout_text, stderr_text
        except Exception as e:
            self._add_log_entry(f"Command execution failed: {e}")
            return False, "", str(e)

    def _is_container_running(self) -> bool:
        """Check if the docling-serve container is running."""
        try:
            cmd = self._get_compose_command()[:1]  # just 'docker' or 'podman'
            result = asyncio.get_event_loop().run_until_complete(
                asyncio.create_subprocess_exec(
                    *cmd, "inspect", "--format", "{{.State.Running}}", CONTAINER_NAME,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            )
            stdout, _ = asyncio.get_event_loop().run_until_complete(result.communicate())
            return stdout.decode().strip() == "true"
        except Exception:
            import subprocess
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER_NAME],
                    capture_output=True, text=True, timeout=5,
                )
                return result.stdout.strip() == "true"
            except Exception:
                return False

    def _add_log_entry(self, message: str) -> None:
        """Add a log entry to the buffer (thread-safe)."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"
        with self._log_lock:
            self._log_buffer.append(entry)
            if len(self._log_buffer) > self._max_log_lines:
                self._log_buffer = self._log_buffer[-self._max_log_lines:]

    def is_running(self) -> bool:
        """Check if docling-serve container is running."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex(("127.0.0.1", self._port))
            s.close()
            running = result == 0
            self._running = running
            if running:
                self._starting = False
            return running
        except Exception:
            self._running = False
            return False

    def check_port_available(self) -> tuple[bool, Optional[str]]:
        """Check if the service port is available."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", self._port))
            sock.close()
            if result == 0:
                return False, f"Port {self._port} is already in use"
            return True, None
        except Exception as e:
            logger.debug(f"Error checking port {self._port}: {e}")
            return True, None

    def get_status(self) -> Dict[str, Any]:
        """Get current status of docling serve."""
        if self._starting:
            return {
                "status": "starting",
                "port": self._port,
                "host": self._host,
                "workers": self._workers,
                "endpoint": None,
                "docs_url": None,
                "ui_url": None,
                "pid": None,
            }

        if self.is_running():
            return {
                "status": "running",
                "port": self._port,
                "host": self._host,
                "workers": self._workers,
                "endpoint": f"http://localhost:{self._port}",
                "docs_url": f"http://localhost:{self._port}/docs",
                "ui_url": f"http://localhost:{self._port}/ui",
                "pid": None,
            }

        return {
            "status": "stopped",
            "port": self._port,
            "host": self._host,
            "workers": self._workers,
            "endpoint": None,
            "docs_url": None,
            "ui_url": None,
            "pid": None,
        }

    async def start(
        self,
        port: int = 5001,
        host: str | None = None,
        enable_ui: bool = False,
        workers: int | None = None,
        timeout: int = 60,
    ) -> Tuple[bool, str]:
        """Start docling-serve container via compose."""
        if self.is_running():
            return False, "Docling serve is already running"

        self._port = port
        if host is not None:
            self._host = host
        if workers is not None:
            self._workers = workers

        self._starting = True
        self._log_buffer = []
        self._add_log_entry("Starting docling-serve container...")

        os.environ["DOCLING_OCR_ENGINE"] = "easyocr"

        try:
            # Pull image first (may take a while on first run)
            self._add_log_entry(f"Pulling image {DOCLING_IMAGE}...")
            success, _, pull_err = await self._run_compose(
                ["pull", CONTAINER_NAME]
            )
            if not success:
                self._add_log_entry(f"Image pull warning (may use cached): {pull_err[:200]}")

            # Start the container
            self._add_log_entry("Starting container...")
            success, _, stderr = await self._run_compose(
                ["up", "-d", CONTAINER_NAME]
            )
            if not success:
                self._starting = False
                return False, f"Failed to start docling-serve container: {stderr[:500]}"

            self._add_log_entry("Container started, waiting for service to be ready...")

            # Wait for the service to start listening
            for i in range(timeout):
                await asyncio.sleep(1.0)

                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.5)
                    result = s.connect_ex(("127.0.0.1", self._port))
                    s.close()
                    if result == 0:
                        self._add_log_entry(f"Docling-serve is ready on port {self._port}")
                        self._starting = False
                        self._running = True
                        return True, f"Docling serve running on http://localhost:{self._port}"
                except Exception:
                    pass

                if (i + 1) % 10 == 0:
                    self._add_log_entry(f"Waiting for startup... ({i + 1}/{timeout}s)")

            # Timeout reached - check if container is still running
            self._starting = False
            _, ps_stdout, _ = await self._run_compose(
                ["ps", "--format", "json", CONTAINER_NAME]
            )
            self._add_log_entry(f"Container status after timeout: {ps_stdout[:200] if ps_stdout else 'unknown'}")

            # Still might be loading models - mark as running if container exists
            self._running = True
            return True, "Docling serve container started (still loading, may take a few minutes)"

        except Exception as e:
            self._starting = False
            self._running = False
            return False, f"Error starting docling serve: {str(e)}"

    async def stop(self) -> Tuple[bool, str]:
        """Stop docling-serve container."""
        if not self.is_running():
            return False, "Docling serve is not running"

        try:
            self._add_log_entry("Stopping docling-serve container...")
            success, _, stderr = await self._run_compose(
                ["stop", CONTAINER_NAME]
            )
            if success:
                self._running = False
                self._add_log_entry("Docling serve container stopped")
                return True, "Docling serve stopped successfully"
            else:
                return False, f"Failed to stop container: {stderr[:500]}"
        except Exception as e:
            self._add_log_entry(f"Error stopping docling serve: {e}")
            return False, f"Error stopping docling serve: {str(e)}"

    async def restart(
        self,
        port: Optional[int] = None,
        host: Optional[str] = None,
        enable_ui: bool = False,
    ) -> Tuple[bool, str]:
        """Restart docling-serve container."""
        if port is None:
            port = self._port
        if host is None:
            host = self._host

        if self.is_running():
            success, msg = await self.stop()
            if not success:
                return False, f"Failed to stop: {msg}"
            await asyncio.sleep(1)

        return await self.start(port, host, enable_ui)

    def add_manual_log_entry(self, message: str) -> None:
        """Add a manual log entry - useful for debugging."""
        self._add_log_entry(f"MANUAL: {message}")

    def get_logs(self, lines: int = 50) -> Tuple[bool, str]:
        """Get logs from the docling-serve container."""
        try:
            import subprocess
            runtime_cmd = self._get_compose_command()[:1]
            result = subprocess.run(
                [*runtime_cmd, "logs", "--tail", str(lines), CONTAINER_NAME],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return True, result.stdout
            elif result.stderr.strip():
                return True, result.stderr
        except Exception as e:
            self._add_log_entry(f"Error fetching container logs: {e}")

        # Fall back to internal log buffer
        if self._log_buffer:
            log_count = min(lines, len(self._log_buffer))
            return True, "\n".join(self._log_buffer[-log_count:])
        return True, "No logs available."

    async def follow_logs(self) -> AsyncIterator[str]:
        """Follow logs from the docling-serve container in real-time."""
        # First yield any existing internal logs
        with self._log_lock:
            if self._log_buffer:
                yield "\n".join(self._log_buffer)

        # Then stream container logs
        try:
            runtime_cmd = self._get_compose_command()[:1]
            process = await asyncio.create_subprocess_exec(
                *runtime_cmd, "logs", "-f", "--tail", "50", CONTAINER_NAME,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)
                if not line:
                    break
                yield line.decode().rstrip()
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            yield f"Error following logs: {e}"
