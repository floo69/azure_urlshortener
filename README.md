# Multicloud URL shortener (Azure)

A small URL shortener: paste a long `http`/`https` URL, get a short code, visit the short link, land on the original page. Data lives in Azure Table Storage. The frontend is one static HTML page.

This repo is the **code**. You configure and deploy Azure resources yourself (no Terraform or CLI scripts here).

## API

The Function uses an **empty HTTP route prefix** (`host.json`) so short links are `https://<host>/<code>`, not `https://<host>/api/<code>`. Triggers are **anonymous** so a visitor does not need a function key.

### Create a short link

`POST /links`

Request:

```json
{ "url": "https://example.com/very/long/path" }
```

Success (`201 Created`):

```json
{
  "code": "aB3xY9k",
  "url": "https://example.com/very/long/path",
  "short_url": "https://<host>/aB3xY9k",
  "created_at": "2026-10-24T08:00:00+00:00"
}
```

Errors:

| Status | When |
|--------|------|
| `400` | Missing/invalid JSON, or URL fails validation (not http/https, no host, too long, junk) |
| `409` | Could not get a unique code after a few collision retries |
| `500` | Table Storage (or other backend) failed |

`OPTIONS /links` is handled for browser CORS preflight (`204`).

The path name `links` is **reserved**. It is never generated as a short code and `GET /links` is never treated as a lookup.

### Follow a short link

`GET /{code}`

| Status | When |
|--------|------|
| `302` | Found. `Location` is the original URL |
| `404` | Unknown, reserved, or badly shaped code |
| `500` | Storage failed |

## Project layout

| Path | Role |
|------|------|
| `api/shortener.py` | Validation, code generation, storage interface, in-memory + Table Storage backends |
| `api/function_app.py` | HTTP in/out only |
| `api/host.json` | Empty `routePrefix` |
| `api/local.settings.example.json` | Placeholder local settings (copy, do not commit secrets) |
| `frontend/` | One-page UI |
| `tests/test_shortener.py` | Unit tests (in-memory, no cloud) |
| `tests/smoke_test.py` | Create + redirect against a running base URL |

## Environment variables

| Name | Required | Meaning |
|------|----------|---------|
| `FUNCTIONS_WORKER_RUNTIME` | yes (Functions) | `python` |
| `AzureWebJobsStorage` | yes (Functions host) | Storage connection the Functions runtime uses. Local example: `UseDevelopmentStorage=true` (Azurite) |
| `STORAGE_BACKEND` | no | `memory` (local/dev) or `azure` (default) |
| `STORAGE_CONNECTION_STRING` | yes if backend is `azure` | Table Storage connection string. Falls back to `AzureWebJobsStorage` if unset |
| `TABLE_NAME` | no | Table name, default `links` |
| `CORS_ALLOWED_ORIGIN` | yes if a browser frontend calls the API | Exact frontend origin, e.g. `http://localhost:5500` or your static-site URL. Not `*` |

Copy `api/local.settings.example.json` to `api/local.settings.json` and fill in values. `local.settings.json` is gitignored.

## Azure portal settings you must configure

Do this yourself after you create the Function App and storage account:

1. **Application settings** (Function App → Configuration / Environment variables)
   - `STORAGE_BACKEND` = `azure`
   - `STORAGE_CONNECTION_STRING` = connection string of the storage account that holds the table
   - `TABLE_NAME` = `links` (or the table name you created)
   - `CORS_ALLOWED_ORIGIN` = the origin of your hosted frontend (scheme + host + port, no trailing slash)
   - `AzureWebJobsStorage` = a storage account connection string (Functions requires this)
2. **CORS** (Function App → CORS)
   - Add the **same** frontend origin. Platform CORS and the app’s `OPTIONS` handler / `CORS_ALLOWED_ORIGIN` should agree, or the browser will block `POST /links`.
3. **Table** — create table `links` in that storage account, or let the first request call `create_table_if_not_exists` (cheap, one table).
4. **Hosting the frontend** — Static Web App, Blob static website, or any static host. Set `API_BASE_URL` in `frontend/app.js` to the Function App URL with **no trailing slash**.

## Run unit tests locally (no Azure)

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install pytest -r api/requirements.txt
python -m pytest tests/test_shortener.py
```

## Run the Function locally

1. Install [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local) and Python 3.9+.
2. `cp api/local.settings.example.json api/local.settings.json` and keep `STORAGE_BACKEND=memory` for a no-cloud run.
3. Set `CORS_ALLOWED_ORIGIN` to whatever origin you use for the HTML (Live Server often uses `http://localhost:5500`).
4. Start the Function:

```bash
cd api
func start
```

5. Open `frontend/index.html` in a browser (or any static server). In `frontend/app.js`, `API_BASE_URL` defaults to `http://localhost:7071`.
6. Optional smoke test against local:

```bash
python tests/smoke_test.py http://localhost:7071
```

If you want local Table Storage instead of memory, run Azurite, set `STORAGE_BACKEND=azure`, and point `STORAGE_CONNECTION_STRING` / `AzureWebJobsStorage` at the emulator. That is optional.

## Smoke test against a deployed app

```bash
python tests/smoke_test.py https://YOUR-FUNCTION.azurewebsites.net
# or
SMOKE_BASE_URL=https://YOUR-FUNCTION.azurewebsites.net python tests/smoke_test.py
```

Creates a link to `https://example.com/` and checks that `GET /{code}` returns `302` with that `Location`.

## Deploy and destroy

_You fill this in with the steps you actually use (portal, CLI, or class notes)._

**Deploy**

- Create resource group, storage account, Function App (Python, consumption or your chosen plan).
- Deploy the contents of `api/` to the Function App.
- Host `frontend/` somewhere and set `API_BASE_URL`.
- Apply the portal app settings and CORS list above.

**Destroy**

- Delete the resource group (or the Function App, storage account, and frontend resource) when you are done so you are not billed.
