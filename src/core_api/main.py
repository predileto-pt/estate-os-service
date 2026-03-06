from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core_api.adapters.api.middleware import JWTAuthMiddleware, RequestLoggingMiddleware
from core_api.adapters.api.routes import auth, companies, email, health, notifications, subscriptions, users
from core_api.config import settings, setup_logging


def create_app(container=None) -> FastAPI:
    setup_logging(settings.log_level)

    app = FastAPI(title="Predileto Core API", version="0.1.0")

    # Middleware (order matters — outermost first)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(JWTAuthMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(companies.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(email.router, prefix="/api/v1")

    # DI container
    if container:
        app.state.container = container

    return app


app = create_app()
