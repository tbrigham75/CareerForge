# Known Limitations

- This is a local single-user application; it is not designed for shared LAN deployment.
- The UI currently has core archive text search; advanced project/date/tag faceted filtering is planned.
- The Git screen provides dry-run exports and safe backend primitives; profile editing and interactive commit/push previews are the next delivery increment.
- ODT import code is intentionally conservative and should be validated against a copy of a source document; manual capture remains the supported fallback.
- Automated UI tests use FastAPI’s local test client rather than an external browser engine.
