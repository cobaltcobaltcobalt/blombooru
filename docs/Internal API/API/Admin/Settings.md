## Admin: Settings

> [!NOTE]
> Last updated: `September 27, 2026`

**Base path:** `/api/admin`

### Get settings

Requires a valid session (JWT only; does not require `admin_mode` cookie).

```
GET /api/admin/settings
```

Returns the current settings object with sensitive fields (`secret_key`, database/redis passwords) redacted.

### Update settings

Requires `require_admin_mode`.

```
PATCH /api/admin/settings
Content-Type: application/json

{
  "app_name": "My Booru",
  "items_per_page": 50,
  "default_sort": "uploaded_at",
  "default_order": "desc",
  "theme": "default_dark",
  "language": "en",
  "external_share_url": null,
  "require_auth": false,
  "blur_explicit_thumbnails": false,
  "sidebar_filter_mode": "rating",
  "sidebar_custom_buttons": [],
  "stripped_cache_max_mb": 0,
  "redis": { "enabled": true, "host": "redis", "port": 6379, "db": 0, "password": null },
  "shared_tags": { "enabled": false, "host": "shared-tag-db", "port": 5432, "name": "shared_tags", "user": "postgres", "password": null }
}
```

All fields are optional; only supplied fields are updated.

> [!NOTE]
> Password fields (`redis.password`, `shared_tags.password`) are returned as `"***"` by `GET /api/admin/settings`. Sending `"***"` back in a PATCH leaves the stored password unchanged. Send `null` to clear a password, or send the new plaintext value to change it.

### Get cache statistics

Requires `require_admin_mode`.

```
GET /api/admin/cache-stats
```

Returns file count and total size in bytes of the metadata-stripped media cache (`media/cache/stripped/`).

**Response:**

```json
{
  "count": 42,
  "size_bytes": 104857600
}
```

### Clear cache

Requires `require_admin_mode`.

```
POST /api/admin/clear-cache
```

Manually cleans up dead stripped-media cache files (files that no longer correspond to any active, metadata-stripped shared media in the database) and migrates any remaining legacy cache files.

**Response:**

```json
{
  "deleted": 5
}
```

### Test Redis connection

Requires `require_admin_mode`.

```
POST /api/admin/test-redis
Content-Type: application/json

{ "host": "redis", "port": 6379, "db": 0, "password": null }
```

**Response:** `{ "success": true }` or `{ "success": false, "error": "..." }`

### Get available themes

No auth required.

```
GET /api/admin/themes
```

**Response:** `{ "themes": ThemeMetadata[], "current_theme": "default_dark" }`

### Get available languages

No auth required.

```
GET /api/admin/languages
```

**Response:** `{ "languages": LanguageMetadata[], "current_language": "en" }`

### Get translations

No auth required.

```
GET /api/admin/translations?lang=en
```

Returns the full translation string map for the requested language (or the currently configured language if `lang` is omitted).
