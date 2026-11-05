"""Read-only local GPU checks for the separately authorized E4 run 4."""

import re
import subprocess

from app.agent.llm.base import ProviderError
from sim.config import E4_GPU_PROBE_TIMEOUT_S, E4_MIN_FREE_VRAM_MIB


def _read(command: list[str]) -> str:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=E4_GPU_PROBE_TIMEOUT_S,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ProviderError("gpu_preflight_unavailable: " + command[0] + " check failed") from None


def require_free_vram() -> int:
    """Require a single NVIDIA GPU with 10 GiB free before loading; never unload anything."""
    output = _read(
        [
            "nvidia-smi",
            "--query-gpu=memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    rows = output.split()
    if len(rows) != 1:
        raise ProviderError("gpu_preflight_unavailable: expected one NVIDIA GPU")
    try:
        free = int(rows[0])
    except ValueError:
        raise ProviderError("gpu_preflight_unavailable: free VRAM is unknown") from None
    if free < E4_MIN_FREE_VRAM_MIB:
        raise ProviderError(
            f"gpu_preflight_vram: {free} MiB free; require {E4_MIN_FREE_VRAM_MIB} MiB "
            "before warm-up. Unload existing models/free VRAM, then retry the preflight."
        )
    return free


def require_full_gpu(model: str) -> None:
    """Check ollama ps after the existing warm-up; never generate or load a model."""
    rows = [
        re.split(r"\s{2,}", row.strip())
        for row in _read(["ollama", "ps"]).splitlines()
        if row.strip()
    ]
    if not rows or "NAME" not in rows[0] or "PROCESSOR" not in rows[0]:
        raise ProviderError("gpu_preflight_unavailable: unrecognized ollama ps output")
    name_col, processor_col = rows[0].index("NAME"), rows[0].index("PROCESSOR")
    matches = [row for row in rows[1:] if len(row) > name_col and row[name_col] == model]
    if len(matches) != 1 or len(matches[0]) <= processor_col:
        raise ProviderError("gpu_preflight_placement: persona model not found in ollama ps")
    processor = " ".join(matches[0][processor_col].split())
    if processor != "100% GPU":
        raise ProviderError(
            f"gpu_preflight_placement: {model} uses {processor}; require 100% GPU after warm-up"
        )
