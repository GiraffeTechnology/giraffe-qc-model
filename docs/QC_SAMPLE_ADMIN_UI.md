# QC Sample Admin UI

The QC Sample Admin page is a backend-rendered internal web interface for
creating and managing QC sample data.

It is **shared by the Pad edition and the Server edition**. No admin UI code
branches by edition. Only inference behaviour differs between editions.

## Technology

| Layer | Technology |
|---|---|
| Router | FastAPI (`src/api/sample_admin_router.py`) |
| Templates | Jinja2 (`src/web/templates/`) |
| Styles | Static CSS (`src/web/static/sample_admin.css`) |
| Interactivity | Vanilla JavaScript (`src/web/static/roi_editor.js`) |
| Forms | HTML forms with PRG (Post/Redirect/Get) pattern |

No React, Next.js, or any client-side build step is required.

## Admin Routes

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/samples` | List all active samples |
| `GET` | `/admin/samples/new` | New sample form |
| `POST` | `/admin/samples` | Create a new SKU/sample |
| `GET` | `/admin/samples/{sku_id}` | Sample detail page |
| `POST` | `/admin/samples/{sku_id}/photos` | Add a standard photo (upload or URL) |
| `POST` | `/admin/samples/{sku_id}/photos/{photo_id}/set-primary` | Set primary photo |
| `POST` | `/admin/samples/{sku_id}/requirements` | Add inspection requirement |
| `POST` | `/admin/samples/{sku_id}/detection-points` | Add detection point |
| `POST` | `/admin/samples/{sku_id}/archive` | Archive the sample (hide from API) |

All routes return HTML. `POST` routes redirect back to the detail or list
page on success (PRG pattern), so browser refresh does not resubmit.

## Sample List Page (`/admin/samples`)

Displays all `status=active` SKUs in a table with:

- Item number
- Name
- Category
- Created date
- Link to the detail page

A "+ New Sample" button links to `/admin/samples/new`.

The page title and heading are:

```
QC Sample Admin
```

Not "Android Pad Sample Admin" or any edition-specific title.

## New Sample Page (`/admin/samples/new`)

Form fields:

| Field | Required |
|---|---|
| `item_number` | Yes |
| `name` | Yes |
| `category` | No |
| `description` | No |

On submit:
- If `(tenant_id, item_number)` is already taken, the form is re-displayed
  with a 409 error message. The duplicate is not saved.
- On success, redirects to the new sample's detail page.

## Sample Detail Page (`/admin/samples/{sku_id}`)

Shows:

- SKU metadata (item number, name, category, description, status)
- **Archive** button — marks the SKU `archived`, hiding it from the
  `/api/v1/sku/search` API immediately.

### Standard Photos Section

Displays all photos for the SKU as cards.

Each card shows:
- Thumbnail or image URL
- Angle / view type
- "Primary" badge if `is_primary=true`
- "Set Primary" button if not already primary

**Add Photo** form (collapsible) — two modes selectable by radio button:

#### Mode A — Upload a file

The browser uploads the image file directly.

- File is written to: `data/qc_samples/{tenant_id}/{sku_id}/photos/{generated_filename}`
- Metadata stored in DB: `local_path`, `sha256`, `mime_type`, `width_px`, `height_px`
- The `data/qc_samples/` directory is listed in `.gitignore` — uploaded images
  are never committed to git.

#### Mode B — Register an existing URL or local path

Provide either `image_url` (HTTP) or `local_path` (factory filesystem path).

Useful when sample images are already stored on the factory LAN and the Pad
will access them via the local network path.

### ROI Editor Section

Appears below the primary photo when `image_url` is set on the primary photo.

A `<canvas>` overlay is drawn over the primary photo image.

**Usage:**

1. Click and drag on the photo to draw a rectangle.
2. The canvas draws a blue-stroked, semi-transparent highlight rectangle.
3. On mouse-up, the rectangle coordinates are converted to normalized
   `{x, y, w, h}` values in the range [0, 1] and written into the output
   textarea.

**Output format:**

```json
{
  "x": 0.10,
  "y": 0.20,
  "w": 0.30,
  "h": 0.25
}
```

Where:
- `x`, `y` are the normalized top-left corner of the rectangle
- `w`, `h` are the normalized width and height
- All values are in [0, 1] relative to the image width and height

The output textarea can also be edited manually. The value is pasted into
the Detection Point form when the operator clicks "Paste from ROI Editor".

### Inspection Requirements Section

Lists all active requirements in a table with: code, title, severity.

**Add Requirement** form (collapsible):

| Field | Required |
|---|---|
| `code` | Yes (e.g. `REQ-STAIN-001`) |
| `title` | Yes |
| `requirement_text` | Yes |
| `severity` | Yes (`minor` / `major` / `critical`) |
| `pass_criteria` | No |
| `sort_order` | No (integer) |

### Detection Points Section

Lists all active detection points with: point code, label, severity, ROI JSON.

**Add Detection Point** form:

| Field | Required |
|---|---|
| `point_code` | Yes (e.g. `DP-FRONT-001`) |
| `label` | Yes |
| `description` | No |
| `roi_json_text` | No (normalized JSON `{x,y,w,h}`) |
| `severity` | Yes |
| `sort_order` | No |

"Paste from ROI Editor" button copies the current ROI textarea content into
the `roi_json_text` field.

If `roi_json_text` is present but not valid JSON, the server returns a
400 error and the detection point is not saved.

## Photo File Storage

Uploaded files are stored under:

```
data/qc_samples/{tenant_id}/{sku_id}/photos/{generated_filename}
```

The directory is created automatically on first upload.

The `.gitignore` entry:

```
data/qc_samples/
```

prevents uploaded sample images from being committed to the repository.

## Pad vs Server Edition

The admin page is identical regardless of which edition the backend is
running under.

The sample DB schema, admin routes, templates, photo upload pipeline, and
ROI editor are all **edition-agnostic**.

See the [Pad vs Server Edition](../README.md#pad-vs-server-edition) section
in the README for the complete comparison table.

## Running the Admin UI

```bash
uv sync --group dev
uv run uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080
```

Open: `http://127.0.0.1:8080/admin/samples`

### Manual Smoke Test Flow

```
1. Open /admin/samples
2. Click "+ New Sample" → create ITEM-FLOWER-001
3. On the detail page, add a standard photo (upload or register URL)
4. Click "Set Primary" on the photo
5. The ROI editor appears below the primary photo
6. Click and drag to draw a rectangle on the photo
7. Click "Add Detection Point" → paste ROI JSON → save
8. Click "Add Requirement" → fill form → save
9. Verify the sample appears at GET /api/v1/sku/search?q=FLOWER
10. Click "Archive" → verify the sample disappears from search
```

## Files

| Path | Purpose |
|---|---|
| `src/api/sample_admin_router.py` | FastAPI router for all `/admin/samples/*` routes |
| `src/web/templates/base.html` | Base Jinja2 template (nav + layout) |
| `src/web/templates/sample_list.html` | Sample list page |
| `src/web/templates/sample_new.html` | New sample form |
| `src/web/templates/sample_detail.html` | Detail page with all sub-sections |
| `src/web/static/sample_admin.css` | Admin stylesheet |
| `src/web/static/roi_editor.js` | Canvas ROI drag-to-draw editor |
| `tests/test_sample_admin.py` | Admin route test coverage |
