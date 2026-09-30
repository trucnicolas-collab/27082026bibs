import pytest_asyncio  # noqa: F401


def pytest_collection_modifyitems(config, items):
    """Marque tous les tests `async def` avec `asyncio` automatiquement."""
    import inspect
    for item in items:
        if inspect.iscoroutinefunction(getattr(item, "function", None)):
            item.add_marker("asyncio")
