"""Portable implementation of local Make targets; no implicit installs in checks."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], directory: str = "") -> None:
    executable = shutil.which(args[0])
    if executable is None:
        raise SystemExit(f"Required executable missing: {args[0]}. See README.md.")
    print(f"+ {' '.join(args)}", flush=True)
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache" / "uv"))
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env.setdefault("PYTEST_DEBUG_TEMPROOT", str(ROOT / ".cache" / "pytest"))
    Path(env["PYTEST_DEBUG_TEMPROOT"]).mkdir(parents=True, exist_ok=True)
    subprocess.run([executable, *args[1:]], cwd=ROOT / directory, env=env, check=True)


def backend(*args: str) -> None:
    run(["uv", "run", "--offline", "--no-sync", *args], "backend")


def frontend(*args: str) -> None:
    run(["npm.cmd" if os.name == "nt" else "npm", *args], "frontend")


def lint() -> None:
    backend("ruff", "check", "app", "tests", "../scripts")
    backend("ruff", "format", "--check", "app", "tests", "../scripts")
    backend("mypy")
    frontend("run", "lint")
    frontend("run", "typecheck")


def tests(marker: str = "not live", frontend_pattern: str | None = None) -> None:
    backend("pytest", "-m", marker)
    args = ["run", "test", "--"]
    if frontend_pattern:
        args.extend(["-t", frontend_pattern])
    frontend(*args)


def dev() -> None:
    uv = shutil.which("uv")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if uv is None or npm is None:
        raise SystemExit("Run make setup with uv and npm installed first.")
    processes: list[subprocess.Popen[bytes]] = []
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".cache" / "uv"))
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    try:
        processes.append(
            subprocess.Popen(
                [uv, "run", "--no-sync", "uvicorn", "app.main:app", "--reload"],
                cwd=ROOT / "backend",
                env=env,
            )
        )
        processes.append(subprocess.Popen([npm, "run", "dev"], cwd=ROOT / "frontend", env=env))
        while all(process.poll() is None for process in processes):
            try:
                processes[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
        raise SystemExit("A development server exited; stopping both servers.")
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main(task: str) -> None:
    if task == "setup":
        run(["uv", "sync", "--locked"], "backend")
        frontend("ci")
    elif task == "db-up":
        run(["docker", "compose", "up", "-d", "--wait", "postgres"])
    elif task == "migrate":
        backend("alembic", "upgrade", "head")
    elif task == "lint":
        lint()
    elif task == "test":
        tests()
    elif task == "check":
        lint()
        tests()
    elif task == "dev":
        dev()
    else:
        raise SystemExit(f"{task} is reserved for a later phase; see STATUS.md and PRD.md.")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
