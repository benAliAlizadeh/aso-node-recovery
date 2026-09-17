from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.version import get_version


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(
            resolved_settings.log_level,
            json_logs=resolved_settings.log_json,
        )
        yield

    application = FastAPI(
        title="ASO Node Recovery",
        version=get_version(),
        lifespan=lifespan,
    )
    application.dependency_overrides[get_settings] = lambda: resolved_settings
    application.include_router(api_router)
    return application


app = create_app()
