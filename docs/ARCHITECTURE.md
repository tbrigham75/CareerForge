# CareerForge: planning milestone

## Product requirements

CareerForge is a single-user, local-first web application for capturing professional work, preserving its supporting context, and converting approved material into reports and portable Markdown. Its central record is an accomplishment with Action, Metric, and Impact (AMI) fields. Capture must be fast enough for raw notes; structured editing, evidence, revision history, projects, search, reports, and controlled exports follow.

The application must work with no network, no AI provider, and no GitHub access. AI drafts are clearly marked **AI Draft — Review Required**, preserve the original note, cannot become approved content without an explicit user action, and may not invent claims. Git exports are optional copies, not the system of record, and must be reviewed before each write, commit, or push.

The version 1 scope excludes automatic publishing, automatic commits/pushes, cloud dependence, enterprise multi-tenancy, and external-system ingestion.

## Recommended architecture

```text
React/Vite browser UI
        | HTTPS / authenticated API only
FastAPI application
  |- PostgreSQL (authoritative metadata/content)
  |- managed filesystem (attachments, reports, export worktrees)
  |- document service (python-docx)
  |- Git export service (validated subprocess commands)
  `- provider adapter -> Ollama-compatible endpoint
```

Use a modular monolith: one backend deployment, one frontend, and PostgreSQL. This minimizes operational cost while keeping boundaries for AI, reporting, and Git explicit. A Redis worker is deferred: synchronous short requests and a database-backed job table cover v1; add a worker only when report/export workload proves it necessary.

**Alternatives.** A server-rendered FastAPI UI would reduce components but compromises the responsive capture/review experience. SQLite is excellent for tests and a disposable developer setup but is not the production default because PostgreSQL has stronger concurrency, full-text search, and migration behavior. A Git library can be evaluated later, but tightly allow-listed `git` subprocess invocations better match the need for status and diff output while avoiding arbitrary command execution.

### Provider boundary

`AIProviderAdapter` will expose health check, model discovery, structured generation, cancellation, and safe diagnostics. Ollama-compatible HTTP is the first adapter. A future OpenAI-compatible, LM Studio, vLLM, or llama.cpp adapter implements the same interface; the capture service does not depend on a specific vendor.

Generation requests carry only selected, user-supplied content plus the versioned prompt template and JSON schema. The backend validates schema output, makes at most one repair request, then saves any still-invalid result only in a safe review area. The browser never receives provider credentials or makes provider requests.

## Data model

All primary entities have UUID primary keys, `created_at`, `updated_at`, and soft-delete metadata where appropriate. Revision records are immutable snapshots/diffs with actor and reason.

| Entity | Key fields / relationships |
| --- | --- |
| `users`, `sessions` | local admin, Argon2id password hash, expiry/revocation |
| `accomplishments` | AMI, narrative, raw note, dates, status, approval state, sensitivity, source, export eligibility, current revision |
| `accomplishment_revisions` | immutable canonical-content history |
| `projects` | dates, goals, outcomes, sensitivity; many-to-many accomplishments |
| `evidence` | type, identifier/URL/path, content hash, sensitivity; many-to-many accomplishments/projects |
| vocabulary tables | categories, tags, skills, competencies, technologies, systems, keywords and join tables |
| `ai_providers` | non-secret settings, local/remote classification, health diagnostics; encrypted credential blob stored separately |
| `prompt_templates` | versioned template body, schema version, active state |
| `ai_generations` | selected provider/model/template, structured draft, raw response policy metadata, hashes, status; never overwrites canonical content |
| `source_imports` | source path/name/hash, import time/status and imported records for idempotence |
| `reports`, `report_items` | definition, generated artifact metadata, ordered source IDs and revision IDs, report-only edits |
| `export_profiles`, `exports`, `export_items` | validated local worktree/profile policy, manifest/result, approval/audit metadata |
| `audit_events` | actor, action, related ID, timing, outcome, safe diagnostics/content hash |

PostgreSQL full-text indexes cover canonical text and explicitly permitted raw-note search. Sensitive content is not placed in diagnostic fields by default. Attachments live outside the database in managed paths, with metadata and hash in `evidence`.

## Deployment model

Docker Compose runs `frontend`, `api`, and `postgres` with persistent volumes for PostgreSQL, attachments, generated reports, logs, templates, and export worktrees. Development uses the same compose topology on Windows; production runs it on Ubuntu behind Caddy, Nginx, or Traefik. The reverse proxy terminates TLS; application cookies are secure when TLS is enabled. Migrations run as a controlled startup job before the API becomes healthy.

Secrets arrive through Docker secrets or environment variables outside Git: an application encryption key, database password, and initial-admin bootstrap secret. `.env.example` contains names and safe placeholders only. Backup/restore later use database dumps plus attachment/report/export-worktree archives and a manifest with version checks.

## Markdown export layout

An export profile targets a dedicated worktree, never the CareerForge application repository by default:

```text
careerforge-archive/
  README.md  INDEX.md
  accomplishments/YYYY/YYYY-MM-DD-slug.md
  projects/  reviews/YYYY/  categories/  skills/  technologies/
  exports/manifest.json
  templates/  .gitignore
```

Each record uses portable YAML front matter with UUID, dates, status, taxonomy, sensitivity, approved export flag, source revision, origin, update time, and safe evidence references. Filename derives from date plus stable slug, while UUID makes updates idempotent. Manifest maps UUID to relative path and exported revision. AI prompts, raw responses, credentials, audit detail, and attachments are excluded unless a future profile explicitly permits a safe subset.

## Security and privacy plan

- Local authentication with Argon2id hashes, server-side sessions, CSRF defense, rate limits, secure/HttpOnly/SameSite cookies, and session revocation.
- Validation/authorization at API boundaries; output encoding; structured errors without secrets; audit event hashes rather than sensitive payloads by default.
- Credentials encrypted at rest using a key from Docker secrets/environment; rotation re-encrypts secrets; UI/API only reveal whether a secret exists.
- Provider URLs are parsed and policy-checked; metadata and dangerous link-local targets are blocked; redirects are rechecked; LAN/VPN/loopback access is opt-in by admin allowlist; timeouts and response-size limits apply.
- Remote AI requires a visible classification and confirmation showing exactly what will be sent. A local-only policy can prohibit it. Confidential/do-not-sync content cannot silently transit to remote providers or Git.
- Sensitivity policy: public-safe may use public-safe profiles; private/internal require a private profile and confirmation; confidential defaults to exclusion; do-not-sync is always excluded.
- Git commands use an allow-listed argument interface with canonicalized paths, validated branch/remote/file names, no shell interpolation, a diff preview, and separate explicit confirmations for write, commit, and push.

## Implementation phases

| Phase | Deliverable and verification |
| --- | --- |
| 0 | Repository skeleton, Compose, environment docs, CI lint/test baseline; verify reproducible local startup. |
| 1 | Auth, migrations, audit foundation, accomplishment/raw-note CRUD and revisions; API/UI and unit/integration tests. |
| 2 | Projects, evidence, taxonomy, archive search/dashboard, safe ODT seed/import; idempotency and authorization tests. |
| 3 | Prompt templates, provider configuration, encrypted secrets, SSRF policy, Ollama adapter, structured draft/review flow; mock-adapter validation tests. |
| 4 | Report builder and deterministic `python-docx` templates; render/structure tests and artifact metadata. |
| 5 | Markdown exporter, profile policy, dry-run/diff/confirm Git flow; idempotency, sensitivity, commit/push safeguard tests. |
| 6 | Backup/restore, operations guides, reverse-proxy deployment, security checklist and end-to-end acceptance review. |

Every implementation phase will state what changed, how to run and test it, migration impact, and the next phase before moving forward.

## Assumptions

1. One trusted user/admin is sufficient for v1; roles beyond administrator are deferred.
2. PostgreSQL and Docker Desktop are acceptable dependencies for the primary deployment.
3. The source ODT remains in its current path and is a reference/example, not a claim-verification source.
4. GitHub use is optional and target repositories may be private; SSH is the preferred authentication route.
5. Attachments can be stored locally with metadata in v1; OCR and automatic external-system imports are deferred.
6. Local/LAN AI endpoints are acceptable only after an administrator configures an explicit endpoint policy.
7. An AI draft is editorial assistance, never evidence; user approval remains mandatory.

## Decisions needed before implementation

1. Confirm the proposed React/Vite + FastAPI + PostgreSQL Docker Compose architecture.
2. Select the initial sign-in bootstrap: an environment-provided administrator password, or a one-time local setup screen protected by a setup token.
3. Confirm whether this repository is the application source only (recommended) and provide a separate local path/repository later for Markdown exports.
4. Confirm default AI policy: offline/no-AI until configured (recommended), or permit local Ollama by default after explicit provider setup.
5. Confirm whether internal records may ever be sent to a remote AI provider; the recommended initial policy is no.

No application implementation begins until these decisions are approved.
