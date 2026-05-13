# Bookings

The `bookings` bounded context manages property visit slots and applicant bookings. Agents create available time slots for showings; screened applicants browse and book them. Slot reservation is atomic via optimistic locking.

**Source:** `src/bookings/`

## Domain entities

| Entity | Description |
|--------|-------------|
| `Slot` | A viewing time window. Status: `AVAILABLE` / `BOOKED` / `CANCELLED`. Belongs to an agent + property + organization. |
| `Booking` | A confirmed appointment linking an applicant to a slot. Status: `CONFIRMED` / `CANCELLED_BY_APPLICANT` / `CANCELLED_BY_AGENT`. |
| `BookingApplicant` | The applicant inside this context. Tracks `external_id` (applicant UUID from `screening`), `supabase_user_id`, and `risk_level`. **Never created with `risk_level=HIGH`** — those are rejected. |

## Cross-context integration

Bookings consume the `APPLICANT_SCREENED.v1` event from `screening`. The bookings-events-queue is bound to the `domain-events` topic exchange with routing-key `APPLICANT_SCREENED.v1` (ADR-008 + 2026-05-13 addendum) and `src/bookings/entrypoints/events_worker.py` runs the shared `EventBusWorker` with `handle_applicant_screened` registered. The handler creates a `BookingApplicant` (idempotent on `external_id`) unless the risk is HIGH, in which case it raises `ApplicantRiskTooHighError` and the applicant is never persisted in this context.

## Feature catalog

### Slots

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [SlotService.create](#slotservicecreate) | `POST /api/v1/admin/slots` | Agent creates a viewing slot |
| [SlotService.find](#slotservicefind) | `GET /api/v1/admin/slots/{slot_id}` | Return one slot |
| [SlotService.list_by_agent](#slotservicelist_by_agent) | `GET /api/v1/admin/slots` | List slots created by an agent |
| [SlotService.list_by_property](#slotservicelist_by_property) | `GET /api/v1/admin/slots?property_id=` | List all slots for a property |
| [SlotService.list_available_by_property](#slotservicelist_available_by_property) | `GET /api/v1/portal/properties/{property_id}/slots` | Public-facing: list available slots from a given time |
| [SlotService.cancel](#slotservicecancel) | `DELETE /api/v1/admin/slots/{slot_id}` | Agent cancels a slot (cascades to booking) |

### Bookings

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [BookingService.create](#bookingservicecreate) | `POST /api/v1/portal/bookings` | Applicant books an available slot (atomic) |
| [BookingService.find](#bookingservicefind) | `GET /api/v1/admin/bookings/{booking_id}` | Return one booking |
| [BookingService.list_by_applicant](#bookingservicelist_by_applicant) | `GET /api/v1/portal/bookings/status` | List the applicant's bookings |
| [BookingService.list_by_organization](#bookingservicelist_by_organization) | `GET /api/v1/admin/bookings` | List org bookings (agent view) |
| [BookingService.cancel_by_applicant](#bookingservicecancel_by_applicant) | `DELETE /api/v1/portal/bookings/{booking_id}` | Applicant cancels their booking |
| [BookingService.cancel_by_agent](#bookingservicecancel_by_agent) | `DELETE /api/v1/admin/bookings/{booking_id}` | Agent cancels an applicant's booking |

### Applicants

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [ApplicantService.create_from_screening](#applicantservicecreate_from_screening) | event: `APPLICANT_SCREENED.v1` | Create a booking-side applicant from the screening event |
| [ApplicantService.find_by_external_id](#applicantservicefind_by_external_id) | internal | Resolve a `BookingApplicant` by screening UUID |
| [ApplicantService.find_by_supabase_user_id](#applicantservicefind_by_supabase_user_id) | internal | Resolve a `BookingApplicant` by Supabase auth ID |

---

## Feature details

### SlotService.create

Create an available slot. `CreateSlotParams.__post_init__` validates `end_time > start_time`.

- **Inputs:** `CreateSlotParams(property_id, agent_user_id, organization_id, start_time, end_time)`
- **Output:** `Slot`
- **Source:** `src/bookings/application/services/slot_service.py`

### SlotService.find

Return a single slot.

- **Inputs:** `slot_id`
- **Output:** `Slot`
- **Source:** `src/bookings/application/services/slot_service.py`

### SlotService.list_by_agent

Paginated list of slots created by an agent within an organization.

- **Inputs:** `agent_user_id`, `organization_id`, `limit`, `offset`
- **Output:** `(list[Slot], int)`

### SlotService.list_by_property

Paginated list of all slots for a property within an organization (any status).

- **Inputs:** `property_id`, `organization_id`, `limit`, `offset`
- **Output:** `(list[Slot], int)`

### SlotService.list_available_by_property

Public-facing query: only `AVAILABLE` slots, only those starting at or after `from_time`.

- **Inputs:** `property_id`, `from_time`, `limit`, `offset`
- **Output:** `(list[Slot], int)`

### SlotService.cancel

Cancel a slot. If the slot has a confirmed booking, the booking is cascaded to `CANCELLED_BY_AGENT` and the applicant is notified.

- **Inputs:** `slot_id`, `agent_user_id`
- **Authorization:** the slot must belong to the requesting agent
- **Side effects:** updates `Slot.status` → `CANCELLED`, finds and cancels any confirmed `Booking`, calls `notifier.slot_cancelled(slot, booking)`

### BookingService.create

Atomically reserve a slot and create a `CONFIRMED` booking. Uses optimistic locking on the slot — if another request booked it first, raises `SlotNotAvailableError`.

- **Inputs:** `slot_id`, `applicant_id`, `notes?`
- **Output:** `Booking`
- **Side effects:** marks slot `BOOKED`, writes `Booking`, calls `notifier.booking_confirmed(booking)`
- **Source:** `src/bookings/application/services/booking_service.py`

### BookingService.find

Return one booking.

- **Inputs:** `booking_id`
- **Output:** `Booking`

### BookingService.list_by_applicant

Paginated list of an applicant's bookings (portal view).

- **Inputs:** `applicant_id`, `limit`, `offset`
- **Output:** `(list[Booking], int)`

### BookingService.list_by_organization

Paginated list of all bookings in an organization (agent view).

- **Inputs:** `organization_id`, `limit`, `offset`
- **Output:** `(list[Booking], int)`

### BookingService.cancel_by_applicant

Applicant cancels their own booking. Verifies that `booking.applicant_id == applicant_id`. Releases the slot back to `AVAILABLE`.

- **Inputs:** `booking_id`, `applicant_id`
- **Side effects:** `Booking.status` → `CANCELLED_BY_APPLICANT`, `Slot.status` → `AVAILABLE`, notifier called
- **Errors:** `BookingNotCancellableError` if booking is not `CONFIRMED`

### BookingService.cancel_by_agent

Agent cancels an applicant's booking. Verifies that `booking.organization_id == organization_id`.

- **Inputs:** `booking_id`, `organization_id`
- **Side effects:** `Booking.status` → `CANCELLED_BY_AGENT`, `Slot.status` → `AVAILABLE`, notifier called

### ApplicantService.create_from_screening

Consume the `APPLICANT_SCREENED.v1` event payload and create a `BookingApplicant`. Idempotent — if a record with the given `external_id` exists, returns it. Raises `ApplicantRiskTooHighError` if the risk is `HIGH`.

- **Inputs:** `data: dict` (the event payload)
- **Output:** `BookingApplicant`
- **Source:** `src/bookings/application/services/applicant_service.py`
- **Event handler:** `src/bookings/adapters/events/handlers.py`

### ApplicantService.find_by_external_id

Resolve a `BookingApplicant` by their screening-context applicant UUID.

- **Inputs:** `external_id`
- **Output:** `BookingApplicant | None`

### ApplicantService.find_by_supabase_user_id

Resolve a `BookingApplicant` by Supabase auth ID. Used after the applicant signs up via the portal.

- **Inputs:** `supabase_user_id`
- **Output:** `BookingApplicant | None`

## Booking tokens

The portal uses signed booking tokens (HMAC) so applicants can book without a full login. Token generation lives in `src/bookings/application/booking_token.py`. Configured via `booking_token_secret` and `booking_link_url` in settings.

## Notifications

`src/bookings/application/ports/notification.py` defines the notifier port. Production uses `LogNotifier` (just logs) — there's no email integration in this context yet. Email notifications about screened applicants come from the `customers` event processor.

## Container

`src/bookings/container.py` wires the three services. Built in `src/shared/entrypoints/bootstrap.py::get_booking_container()` and stored on `app.state.booking_container`.
