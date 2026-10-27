from .common.runtime import execute, entrypoint
from .trend_engine import collect, collect_fallback, settings


async def run_actor(actor):
    """No URLs means real public trend APIs; supplied URLs select product extraction."""
    return await execute(actor, settings, lambda config: collect(config, actor),
                         'trend-item-extracted', 'cn-trend-radar-ppe', collect_fallback)


def main():
    entrypoint(run_actor)
