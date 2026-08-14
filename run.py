"""Convenience launcher. Equivalent to `python -m app.main`."""
from app.main import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
