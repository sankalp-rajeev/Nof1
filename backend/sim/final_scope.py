"""Explicit capability held only while the human-triggered final command executes."""

from contextvars import ContextVar

from sim.config import DEV_SEED_MAX, DEV_SEED_MIN, FINAL_A

FINAL_SEEDS_ALLOWED: ContextVar[bool] = ContextVar("final_seeds_allowed", default=False)


def permitted_seed(seed: int) -> bool:
    return DEV_SEED_MIN <= seed <= DEV_SEED_MAX or (FINAL_SEEDS_ALLOWED.get() and seed in FINAL_A)
