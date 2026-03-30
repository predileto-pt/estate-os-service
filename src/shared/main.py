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
    portal_auth,
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
from applicant_screening.adapters.api.routes import (
    applicants as screening_applicants,
    intake_forms,
    submissions,
)
from properties_listing.adapters.api.routes import listings
from booking_management.adapters.api.routes import (
    bookings as booking_admin,
    portal_bookings,
    slots,
)
from contract_intelligence.adapters.api.routes import (
    generated_contracts,
    review as contract_review,
    source_documents,
    template_versions,
)


def create_app(
    container=None,
    property_container=None,
    applicant_screening_container=None,
    listing_container=None,
    booking_container=None,
    contract_intelligence_container=None,
) -> FastAPI:
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "container") or app.state.container is None:
            from shared.entrypoints.bootstrap import (
                get_applicant_screening_container,
                get_booking_container,
                get_container,
                get_contract_intelligence_container,
                get_listing_container,
                get_property_container,
            )

            app.state.container = await get_container()
            app.state.property_container = await get_property_container()
            app.state.applicant_screening_container = await get_applicant_screening_container()
            listing_cont = await get_listing_container()
            app.state.listing_container = listing_cont
            app.state.booking_container = await get_booking_container()
            app.state.contract_intelligence_container = await get_contract_intelligence_container()
            # Expose document storage for image presigned URLs in listing context
            app.state._listing_document_storage = getattr(
                app.state.property_container, "document_storage", None
            )
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
            {"name": "property-listings", "description": "Public property listings"},
            {
                "name": "applicant-submissions",
                "description": "Applicant document submission and screening",
            },
            {"name": "intake-form-requests", "description": "Intake form request management"},
            {"name": "applicants", "description": "Applicant listing and details"},
            {"name": "booking-slots", "description": "Visit slot management"},
            {"name": "booking-bookings", "description": "Visit booking management"},
            {"name": "portal-bookings", "description": "Portal booking for applicants"},
            {
                "name": "contract-source-documents",
                "description": "Contract source document management",
            },
            {"name": "contract-review", "description": "Contract section and field review"},
            {"name": "contract-templates", "description": "Contract template version management"},
            {"name": "contract-generation", "description": "Contract generation from templates"},
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

    # Health (no prefix change)
    app.include_router(health.router, prefix="/api/v1")

    # Admin routes (agency staff, org-scoped)
    app.include_router(auth.router, prefix="/api/v1/admin")
    app.include_router(users.router, prefix="/api/v1/admin")
    app.include_router(organizations.router, prefix="/api/v1/admin")
    app.include_router(memberships.router, prefix="/api/v1/admin")
    app.include_router(invitations.router, prefix="/api/v1/admin")
    app.include_router(subscriptions.router, prefix="/api/v1/admin")
    app.include_router(notifications.router, prefix="/api/v1/admin")
    app.include_router(email.router, prefix="/api/v1/admin")
    app.include_router(properties.router, prefix="/api/v1/admin")
    app.include_router(property_owners.router, prefix="/api/v1/admin")
    app.include_router(property_prices.router, prefix="/api/v1/admin")
    app.include_router(property_images.router, prefix="/api/v1/admin")
    app.include_router(property_amenities.router, prefix="/api/v1/admin")
    app.include_router(extraction_jobs.router, prefix="/api/v1/admin")

    # Portal routes (property seekers, no org)
    app.include_router(portal_auth.router, prefix="/api/v1/portal")

    # Public property listings (no auth)
    app.include_router(listings.router, prefix="/api/v1/listings")

    # Applicant screening — portal (no auth: intake form submission)
    app.include_router(submissions.router, prefix="/api/v1/portal")

    # Applicant screening — admin (JWT auth: agency staff)
    app.include_router(intake_forms.router, prefix="/api/v1/admin")
    app.include_router(screening_applicants.router, prefix="/api/v1/admin")

    # Booking management — admin (JWT auth: agency staff)
    app.include_router(slots.router, prefix="/api/v1/admin")
    app.include_router(booking_admin.router, prefix="/api/v1/admin")

    # Booking management — portal (applicant-facing)
    app.include_router(portal_bookings.router, prefix="/api/v1/portal")

    # Contract intelligence — admin (JWT auth: agency staff)
    app.include_router(source_documents.router, prefix="/api/v1/admin")
    app.include_router(contract_review.router, prefix="/api/v1/admin")
    app.include_router(template_versions.router, prefix="/api/v1/admin")
    app.include_router(generated_contracts.router, prefix="/api/v1/admin")

    # DI container (set by tests; production uses lifespan)
    if container:
        app.state.container = container
    if property_container:
        app.state.property_container = property_container
    if applicant_screening_container:
        app.state.applicant_screening_container = applicant_screening_container
    if listing_container:
        app.state.listing_container = listing_container
    if booking_container:
        app.state.booking_container = booking_container
    if contract_intelligence_container:
        app.state.contract_intelligence_container = contract_intelligence_container

    return app


app = create_app()
