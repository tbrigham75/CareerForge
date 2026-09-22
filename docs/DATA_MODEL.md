# Data model

The core model includes User, Accomplishment, AccomplishmentRevision, AIDraft, Project, EvidenceReference, Category, Tag, Technology, Skill, Competency, Report, ReportItem, ReportTemplate, AIProvider, PromptTemplate, GitRepositoryProfile, ExportRun, AuditEvent, AttachmentMetadata, and ImportRun.

Accomplishments retain an immutable UUID, raw note, Action/Metric/Impact, status, approval, source provenance, sensitivity, optional export flag, timestamps, soft-delete state, and an immutable revision snapshot on every save/archive action.
