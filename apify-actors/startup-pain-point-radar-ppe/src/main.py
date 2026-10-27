from .common.runtime import execute, entrypoint
from .radar_engine import collect, collect_fallback, settings


async def run_actor(actor):
    """Zero input collects live HN/GitHub; only explicit offline/source failure is free demo."""
    return await execute(actor, settings, lambda config: collect(config, actor),
                         'pain-point-extracted', 'startup-pain-point-radar-ppe', collect_fallback)


def main():
    entrypoint(run_actor)
