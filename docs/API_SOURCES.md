# ZERINET API sources

## AniLibria API v1

Status: configured as the primary anime metadata and episode-source adapter. Runtime availability and redistribution permissions must be verified before public launch.

- Primary base: `https://anilibria.top/api/v1`
- Official mirror: `https://api.anilibria.app/api/v1`
- Current documentation: `https://anilibria.top/api/docs/v1`
- Mirror documentation: `https://api.anilibria.app/api/docs/v1/`

The legacy documentation in the old `anilibria/docs` repository explicitly marks its old API as deprecated and points developers to the current v1 documentation. Do not build new code against the legacy `/public/api/index.php` interface or old v2/v3 routes.

### Current integration flow

Browser -> same-origin `/aniapi/*` -> Python backend proxy -> configured official API v1 upstream.

The same-origin route avoids relying on browser CORS access and gives the backend a single place to manage upstream selection and timeouts.

### Frontend routes currently used

- `/app/search/releases`
- `/anime/catalog/releases`
- `/anime/releases/{alias}`
- `/anime/releases/episodes/{episodeId}`

The UI must handle empty results, unavailable mirrors, missing episode streams, and upstream errors. A successful metadata response does not guarantee that a playable video stream is available.

### Provider boundaries

AniLibria data is not the canonical identity store for ZERINET. Persist external IDs and map releases to ZERINET's internal anime IDs. Keep provider-specific aliases and episode IDs in provider mapping tables so another metadata or video provider can be added without changing the player.

Do not assume that API availability grants rights to redistribute posters, metadata, or video. Before public/commercial launch, review the provider's current terms and obtain any required content permissions. Never proxy blocked or unavailable content as a workaround.

## Kodik

Kodik remains an optional, separate adapter. Its token is server-only and must be supplied through `KODIK_TOKEN`. Never commit the token, include it in browser code, or return it from status endpoints.

If a Kodik token was previously committed to a public repository, deleting the file is not enough: revoke/rotate the token because Git history may still contain it.
