from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.api.middleware import JWTAuthMiddleware, RequestLoggingMiddleware
from shared.config import settings, setup_logging
from customer_management.adapters.api.routes import (
    auth,
    email,
    health,
    invitations,
    memberships,
    notifications,
    organizations,
    subscriptions,
    users,
)
from property_management.adapters.api.routes import (
    extraction_jobs,
    properties,
    property_amenities,
    property_images,
    property_owners,
    property_prices,
)


def create_app(container=None, property_container=None) -> FastAPI:
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "container") or app.state.container is None:
            from shared.entrypoints.bootstrap import get_container, get_property_container

            app.state.container = await get_container()
            app.state.property_container = await get_property_container()
        yield

    app = FastAPI(
        title="Predileto Core API",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Core backend service for the Predileto platform. "
            "Handles user registration, organization management, subscriptions, "
            "notifications, and email."
        ),
        openapi_tags=[
            {"name": "health", "description": "Health check"},
            {"name": "auth", "description": "Authentication and user registration"},
            {"name": "users", "description": "User profile management"},
            {"name": "organizations", "description": "Organization management"},
            {"name": "memberships", "description": "Organization membership management"},
            {"name": "invitations", "description": "Member invitation management"},
            {"name": "subscriptions", "description": "Subscription and plan management"},
            {"name": "notifications", "description": "In-app notification management"},
            {"name": "email", "description": "Transactional email sending"},
            {"name": "properties", "description": "Property management"},
            {"name": "property-owners", "description": "Property owner management"},
            {"name": "extraction-jobs", "description": "AI-powered property extraction"},
            {"name": "property-prices", "description": "Property price management"},
            {"name": "property-images", "description": "Property image management"},
            {"name": "property-amenities", "description": "Property amenity discovery"},
        ],
    )

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
    app.include_router(organizations.router, prefix="/api/v1")
    app.include_router(memberships.router, prefix="/api/v1")
    app.include_router(invitations.router, prefix="/api/v1")
    app.include_router(subscriptions.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(email.router, prefix="/api/v1")
    app.include_router(properties.router, prefix="/api/v1")
    app.include_router(property_owners.router, prefix="/api/v1")
    app.include_router(property_prices.router, prefix="/api/v1")
    app.include_router(property_images.router, prefix="/api/v1")
    app.include_router(property_amenities.router, prefix="/api/v1")
    app.include_router(extraction_jobs.router, prefix="/api/v1")

    # DI container (set by tests; production uses lifespan)
    if container:
        app.state.container = container
    if property_container:
        app.state.property_container = property_container

    return app


app = create_app()
