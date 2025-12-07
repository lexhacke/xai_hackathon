"""Main FastAPI application entry point.

Configures and initializes the FastAPI application with routes, middleware,
and error handling. Responsible for setting up the application context,
including logging, Sentry integration, and database sessions.

Initializes and configures the FastAPI application with middleware, error handlers,
and routers. Entry point for the backend service.

Uses SQLModel metadata to create tables directly instead of Alembic migrations.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.api.routes import streaming
from app.core.config import settings
from app.core.log_config import logger


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate a unique operation ID for OpenAPI documentation.

    Creates a consistent, readable ID based on the route's tag and name.
    Used for better OpenAPI documentation and client generation.

    Args:
        route: FastAPI route object

    Returns:
        Unique operation ID string combining tag and route name
    """
    return f"{route.tags[0]}-{route.name}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan context.

    This context manager runs tasks before the application starts,
    and after it shuts down.
    """
    # Pre-startup initialization task
    try:
        logger.info("FastAPI application starting up")

        # Warm-up database connection to fail fast if unreachable
        # Skip in local/dev mode if database is not available
        try:
            from sqlalchemy import text

            from app.core.db import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection verified")
        except Exception as db_error:
            if settings.ENVIRONMENT == "local":
                logger.warning(f"Database connection failed (skipping in local mode): {db_error}")
            else:
                raise

        # Validate AI service API keys
        _validate_ai_services()

        yield
    finally:
        # Shutdown tasks
        logger.info("FastAPI application shutting down")
    # Cleanup on shutdown is handled in the finally block above


def _validate_ai_services() -> None:
    """Validate that required AI service API keys are configured."""
    import os

    services = {
        "Moondream": settings.MOONDREAM_API_KEY,
        "Mem0": settings.MEM0_API_KEY,
        "Deepgram": os.environ.get("DEEPGRAM_API_KEY"),
        "Hume": os.environ.get("HUME_API_KEY"),
        "xAI (Grok)": os.environ.get("XAI_API_KEY"),
    }

    for name, key in services.items():
        if key:
            # Mask the key for logging (show first 4 chars)
            masked = f"{key[:4]}...{key[-4:]}" if len(key) > 8 else "****"
            logger.info(f"{name} API key configured: {masked}")
        else:
            logger.warning(f"{name} API key NOT configured - service will be disabled")


def get_application() -> FastAPI:
    """Create and configure the FastAPI application.

    Sets up the FastAPI instance with title, version, CORS middleware,
    and API routers. This factory pattern allows for easier testing
    and application configuration.

    Returns:
        Configured FastAPI application instance
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description=settings.DESCRIPTION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url="/docs",
        generate_unique_id_function=custom_generate_unique_id,
        lifespan=lifespan,
    )

    # Set all CORS enabled origins
    if settings.all_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.all_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix=settings.API_V1_STR)
    app.include_router(streaming.router)

    return app


# Sentry integration is now handled in app.core._logging module
# This ensures Sentry is initialized before any log messages are sent
logger.info(f"Application initialized in {settings.ENVIRONMENT} environment")

app = get_application()
