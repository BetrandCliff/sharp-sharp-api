# Sharp Sharp Delivery API

FastAPI backend for Sharp-Sharp's authentication, profiles, supplier/driver catalog, gas and errant orders, activities, chat, calls, delivery locations, payments, and chat-audio upload signing. PostgreSQL tables are managed with SQLAlchemy and Alembic.

The Flutter code still contains direct Supabase data/auth/realtime calls. This backend provides the corresponding API, but the Flutter data sources must be migrated to these routes before Supabase can be removed; changing `API_BASE_URL` alone only switches the already-centralized payment, delivery, and signaling calls. Payment and delivery HTTP requests must send `Authorization: Bearer <backend access_token>`. WebSocket requests must include `?token=<backend access_token>`. The current Flutter payment, location, and signaling clients do not attach those credentials, and Supabase access tokens are not accepted by this API, so those calls need client-side auth wiring before they can succeed.

## Run locally (Windows)

Requires Python 3.10 or newer.

```powershell
cd "$HOME\Desktop\python\sharp_sharp_delivery_api"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d db
alembic upgrade head
python -m app.bootstrap_admin
```

The bootstrap command promotes an existing account or creates the first administrator. Set `JWT_SECRET_KEY`, SMTP settings, and a Stripe test key in `.env`; the example database URL connects to local Docker PostgreSQL. Then run:

```powershell
uvicorn app.main:app --reload --env-file .env --host 0.0.0.0 --port 8000
```

API docs are at `http://127.0.0.1:8000/docs`. From the Android emulator use `http://10.0.2.2:8000`; a physical phone needs the computer's LAN IP. WebSocket endpoints accept a backend access token as the `token` query parameter and require HTTPS/WSS in deployed environments.

## API surface

- Authentication: `/auth/register`, `/auth/verify-email`, `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`, `GET /auth/profile`, `PUT /auth/profile`, `/auth/request-password-reset`, `/auth/reset-password`. Registration requires email and password and also accepts optional `userName` (or `fullNames`/`name`) and `phone`, which are saved to the profile. Registration/login accept the Flutter form's 6-character minimum password; password reset requires at least 8 characters.
- Catalog/admin: `/companies/suppliers`, `/drivers/{driver_id}`, and admin-only `/admin/companies`, `/admin/drivers`, `/admin/users/{user_id}/role`.
- Orders/activity: `/errants`, `/gas-orders`, `/activities`, with owner/assigned-driver checks and `/ws/orders/{order_id}` status events.
- Chat/calls: `/conversations`, message CRUD under `/conversations/{id}/messages`, `/calls`, `/ws/conversations/{id}`, `/ws/calls/{id}`, plus `/ws/signaling` WebRTC relay.
- Delivery: authenticated `POST /delivery/update-location`, latest/history GET routes, and `/ws/delivery/{delivery_id}`.
- Payments/storage: authenticated `POST /payment/intent`, `GET /payments`, signed `POST /storage/audio/upload-url`, and Stripe `POST /payment/webhook`.

The existing Flutter payment endpoint expects `clientSecret`; it now also receives `paymentIntentId`. Upload clients must PUT bytes to the returned `upload_url` using the returned `content_type` and `content_length` headers. Configure the R2 bucket's CORS policy to allow the app's origins and PUT requests.

## Production database

Set `DATABASE_URL` to the Neon PostgreSQL connection string and provide `JWT_SECRET_KEY`, SMTP, Stripe, and R2 settings through the production secret manager. Run `alembic upgrade head` as a release step. Standard `postgresql://` Neon URLs are supported by psycopg. R2 is accessed through its S3-compatible endpoint; `R2_PUBLIC_URL` should be the configured public/custom domain. Never copy production credentials into local `.env` or commit them.

## Before deployment

WebSocket subscriptions are process-local; use shared pub/sub such as Redis before running multiple API instances. The current mobile payment flow supplies an amount, so production must calculate it from trusted order data and verify Stripe webhooks. Configure restrictive `CORS_ORIGINS`, SMTP delivery, R2 bucket CORS, HTTPS, backups, and monitoring. Existing Supabase users need a password reset or re-registration because Supabase password hashes cannot be migrated into this auth service.

Run tests with `pytest`.
"# sharp-sharp-api" 
