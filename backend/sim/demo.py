"""Find and pin the first eligible, beneficial, detectable synthetic demo history."""

from app.stats.config import N_PERM
from sim.config import DEV_SEED_MAX
from sim.runner import run_scan
from sim.world import World, generate_world, world_to_panel

# First qualifying seed found by find_demo_seed under the fixed P3 world model.
DEMO_SEED = 283


def find_demo_seed(*, max_seed: int = DEV_SEED_MAX) -> int:
    if not 0 <= max_seed <= DEV_SEED_MAX:
        raise ValueError("Demo search is restricted to dev seeds")
    for seed in range(max_seed + 1):
        world = generate_world(seed, days=45)
        if world.truth.patient_type != "single_effect" or len(world.truth.effects) != 1:
            continue
        effect = world.truth.effects[0]
        if effect.beta != -3 or effect.lag != 0:
            continue
        output = run_scan(world_to_panel(world), identity=f"demo-{seed}", n_perm=N_PERM)
        if any(
            pattern.exposure == effect.exposure and pattern.lag_days == 0 and pattern.effect < 0
            for pattern in output.patterns
        ):
            return seed
    raise RuntimeError("No qualifying demo in the searched dev seeds")


def demo_world() -> World:
    return generate_world(DEMO_SEED, days=45)
