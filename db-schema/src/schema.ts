import { sql } from 'drizzle-orm'
import {
  boolean,
  index,
  doublePrecision,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  unique,
  uniqueIndex,
  varchar,
} from 'drizzle-orm/pg-core'

// ===========================================================================
// 量子实验平台 — 内置 Supabase 数据库 Schema
// 仅用于 drizzle-kit generate 生成建表 SQL；业务 CRUD 走 Supabase Data API。
// 字段严格对齐 platform_app/models.py，RLS 默认拒绝（enableRLS），策略待认证接入后细化。
// ===========================================================================

export const users = pgTable(
  'users',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    username: varchar('username', { length: 80 }).notNull(),
    name: varchar('name', { length: 120 }).notNull(),
    role: varchar('role', { length: 20 }).notNull(),
    password_hash: text('password_hash').notNull(),
    active: boolean('active').default(true).notNull(),
    must_change_password: boolean('must_change_password').default(false).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    uniqueIndex('uq_users_username').on(table.username),
    index('ix_users_role').on(table.role),
  ],
).enableRLS()

export const courses = pgTable(
  'courses',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    teacher_id: varchar('teacher_id', { length: 64 }).references(() => users.id),
    name: varchar('name', { length: 160 }).notNull(),
    min_experiments_required: integer('min_experiments_required').default(3).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    index('ix_courses_teacher_id').on(table.teacher_id),
  ],
).enableRLS()

export const experiments = pgTable(
  'experiments',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    code: varchar('code', { length: 24 }).notNull(),
    title: varchar('title', { length: 160 }).notNull(),
    order_no: integer('order_no').default(0).notNull(),
    retired: boolean('retired').default(false).notNull(),
  },
  (table) => [
    uniqueIndex('uq_experiments_code').on(table.code),
  ],
).enableRLS()

export const courseExperiments = pgTable(
  'course_experiments',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    course_id: varchar('course_id', { length: 64 }).notNull().references(() => courses.id),
    experiment_id: varchar('experiment_id', { length: 64 }).notNull().references(() => experiments.id),
    position: integer('position').default(0).notNull(),
    active: boolean('active').default(true).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    unique('uq_course_experiments_course_exp').on(table.course_id, table.experiment_id),
    index('ix_course_experiments_course').on(table.course_id),
    index('ix_course_experiments_experiment').on(table.experiment_id),
  ],
).enableRLS()

export const enrollments = pgTable(
  'enrollments',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    course_id: varchar('course_id', { length: 64 }).notNull().references(() => courses.id),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
  },
  (table) => [
    unique('uq_enrollments_course_student').on(table.course_id, table.student_id),
    index('ix_enrollments_course').on(table.course_id),
    index('ix_enrollments_student').on(table.student_id),
  ],
).enableRLS()

export const fileAssets = pgTable(
  'file_assets',
  {
    sha256: varchar('sha256', { length: 64 }).primaryKey(),
    object_key: varchar('object_key', { length: 200 }).notNull(),
    original_name: varchar('original_name', { length: 240 }).notNull(),
    content_type: varchar('content_type', { length: 120 }).notNull(),
    size: integer('size').notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    uniqueIndex('uq_file_assets_object_key').on(table.object_key),
  ],
).enableRLS()

export const experimentVersions = pgTable(
  'experiment_versions',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    experiment_id: varchar('experiment_id', { length: 64 }).notNull().references(() => experiments.id),
    version_no: integer('version_no').default(1).notNull(),
    status: varchar('status', { length: 20 }).default('draft').notNull(),
    definition: jsonb('definition').default(sql`'{}'::jsonb`).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
    published_at: timestamp('published_at', { withTimezone: true }),
  },
  (table) => [
    unique('uq_experiment_versions_exp_version').on(table.experiment_id, table.version_no),
    index('ix_experiment_versions_experiment').on(table.experiment_id),
    index('ix_experiment_versions_status').on(table.status),
  ],
).enableRLS()

export const experimentDrafts = pgTable(
  'experiment_drafts',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    teacher_id: varchar('teacher_id', { length: 64 }).notNull().references(() => users.id),
    experiment_id: varchar('experiment_id', { length: 64 }).references(() => experiments.id),
    status: varchar('status', { length: 20 }).default('draft').notNull(),
    code: varchar('code', { length: 24 }).notNull(),
    title: varchar('title', { length: 160 }).notNull(),
    definition: jsonb('definition').default(sql`'{}'::jsonb`).notNull(),
    source_asset_hash: varchar('source_asset_hash', { length: 64 }).references(() => fileAssets.sha256),
    source_kind: varchar('source_kind', { length: 30 }).default('prompt').notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    index('ix_experiment_drafts_teacher').on(table.teacher_id),
    index('ix_experiment_drafts_experiment').on(table.experiment_id),
    index('ix_experiment_drafts_status').on(table.status),
  ],
).enableRLS()

export const quizAssignments = pgTable(
  'quiz_assignments',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    course_id: varchar('course_id', { length: 64 }).notNull().references(() => courses.id),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
    experiment_version_id: varchar('experiment_version_id', { length: 64 }).notNull().references(() => experimentVersions.id),
    questions: jsonb('questions').notNull(),
    answers: jsonb('answers').default(sql`'{}'::jsonb`).notNull(),
    attempt_no: integer('attempt_no').default(1).notNull(),
    history: jsonb('history').default(sql`'[]'::jsonb`).notNull(),
    signature: varchar('signature', { length: 64 }).notNull(),
    frozen_at: timestamp('frozen_at', { withTimezone: true }).defaultNow().notNull(),
    completed_at: timestamp('completed_at', { withTimezone: true }),
  },
  (table) => [
    unique('uq_quiz_course_version_signature').on(table.course_id, table.experiment_version_id, table.signature),
    unique('uq_quiz_course_student_version').on(table.course_id, table.student_id, table.experiment_version_id),
    index('ix_quiz_student').on(table.student_id),
    index('ix_quiz_experiment_version').on(table.experiment_version_id),
  ],
).enableRLS()

export const evaluations = pgTable(
  'evaluations',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    fingerprint: varchar('fingerprint', { length: 64 }).notNull(),
    evaluator_version: varchar('evaluator_version', { length: 40 }).notNull(),
    model: varchar('model', { length: 120 }).default('deterministic-fallback').notNull(),
    score: integer('score').notNull(),
    feedback: text('feedback').notNull(),
    result: jsonb('result').default(sql`'{}'::jsonb`).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    unique('uq_evaluations_fingerprint_version').on(table.fingerprint, table.evaluator_version),
    index('ix_evaluations_fingerprint').on(table.fingerprint),
  ],
).enableRLS()

export const submissionRevisions = pgTable(
  'submission_revisions',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    request_id: varchar('request_id', { length: 80 }).notNull(),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
    course_id: varchar('course_id', { length: 64 }).references(() => courses.id),
    experiment_version_id: varchar('experiment_version_id', { length: 64 }).notNull().references(() => experimentVersions.id),
    revision_no: integer('revision_no').notNull(),
    status: varchar('status', { length: 24 }).default('submitted').notNull(),
    payload: jsonb('payload').notNull(),
    result_value: doublePrecision('result_value').notNull(),
    relative_error: doublePrecision('relative_error').notNull(),
    deterministic_score: integer('deterministic_score').notNull(),
    passed: boolean('passed').notNull(),
    fingerprint: varchar('fingerprint', { length: 64 }).notNull(),
    evaluation_id: varchar('evaluation_id', { length: 64 }).references(() => evaluations.id),
    submitted_at: timestamp('submitted_at', { withTimezone: true }).defaultNow().notNull(),
    withdrawn_at: timestamp('withdrawn_at', { withTimezone: true }),
    supersedes_id: varchar('supersedes_id', { length: 64 }).references(() => submissionRevisions.id),
  },
  (table) => [
    unique('uq_submission_student_request').on(table.student_id, table.request_id),
    unique('uq_submission_course_student_version_revision').on(
      table.course_id,
      table.student_id,
      table.experiment_version_id,
      table.revision_no,
    ),
    index('ix_submission_student').on(table.student_id),
    index('ix_submission_course').on(table.course_id),
    index('ix_submission_experiment_version').on(table.experiment_version_id),
    index('ix_submission_fingerprint').on(table.fingerprint),
  ],
).enableRLS()

export const reportDrafts = pgTable(
  'report_drafts',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
    course_id: varchar('course_id', { length: 64 }).notNull().references(() => courses.id),
    experiment_version_id: varchar('experiment_version_id', { length: 64 }).notNull().references(() => experimentVersions.id),
    source_revision_id: varchar('source_revision_id', { length: 64 }).references(() => submissionRevisions.id),
    status: varchar('status', { length: 20 }).default('active').notNull(),
    content: jsonb('content').default(sql`'{}'::jsonb`).notNull(),
    asset_hashes: jsonb('asset_hashes').default(sql`'[]'::jsonb`).notNull(),
    lock_version: integer('lock_version').default(1).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
    updated_at: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    unique('uq_report_drafts_course_student_version').on(table.course_id, table.student_id, table.experiment_version_id),
    index('ix_report_drafts_student').on(table.student_id),
    index('ix_report_drafts_source_revision').on(table.source_revision_id),
    index('ix_report_drafts_status').on(table.status),
  ],
).enableRLS()

export const studentExperimentProgress = pgTable(
  'student_experiment_progress',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    course_id: varchar('course_id', { length: 64 }).notNull().references(() => courses.id),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
    experiment_version_id: varchar('experiment_version_id', { length: 64 }).notNull().references(() => experimentVersions.id),
    selected: boolean('selected').default(false).notNull(),
    completed_steps: jsonb('completed_steps').default(sql`'[]'::jsonb`).notNull(),
    step_data: jsonb('step_data').default(sql`'{}'::jsonb`).notNull(),
    asset_hashes: jsonb('asset_hashes').default(sql`'[]'::jsonb`).notNull(),
    completed_at: timestamp('completed_at', { withTimezone: true }),
    updated_at: timestamp('updated_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    unique('uq_student_progress_course_student_version').on(table.course_id, table.student_id, table.experiment_version_id),
    index('ix_student_progress_student').on(table.student_id),
    index('ix_student_progress_experiment_version').on(table.experiment_version_id),
  ],
).enableRLS()

export const reviews = pgTable(
  'reviews',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    submission_id: varchar('submission_id', { length: 64 }).notNull().references(() => submissionRevisions.id),
    teacher_id: varchar('teacher_id', { length: 64 }).notNull().references(() => users.id),
    private_score: integer('private_score').notNull(),
    private_comment: text('private_comment').default('').notNull(),
    decision: varchar('decision', { length: 20 }).default('approved').notNull(),
    superseded: boolean('superseded').default(false).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    index('ix_reviews_submission').on(table.submission_id),
    index('ix_reviews_teacher').on(table.teacher_id),
    index('ix_reviews_decision').on(table.decision),
  ],
).enableRLS()

export const awards = pgTable(
  'awards',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    student_id: varchar('student_id', { length: 64 }).notNull().references(() => users.id),
    experiment_version_id: varchar('experiment_version_id', { length: 64 }).notNull().references(() => experimentVersions.id),
    score: integer('score').notNull(),
    awarded_at: timestamp('awarded_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    unique('uq_awards_student_version').on(table.student_id, table.experiment_version_id),
    index('ix_awards_student').on(table.student_id),
    index('ix_awards_experiment_version').on(table.experiment_version_id),
  ],
).enableRLS()

export const auditEvents = pgTable(
  'audit_events',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    actor_id: varchar('actor_id', { length: 64 }),
    action: varchar('action', { length: 80 }).notNull(),
    entity_type: varchar('entity_type', { length: 60 }).notNull(),
    entity_id: varchar('entity_id', { length: 64 }).notNull(),
    detail: jsonb('detail').default(sql`'{}'::jsonb`).notNull(),
    created_at: timestamp('created_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    index('ix_audit_events_actor').on(table.actor_id),
    index('ix_audit_events_action').on(table.action),
  ],
).enableRLS()

export const legacyArchives = pgTable(
  'legacy_archives',
  {
    id: varchar('id', { length: 64 }).primaryKey(),
    source_name: varchar('source_name', { length: 240 }).notNull(),
    sha256: varchar('sha256', { length: 64 }).notNull(),
    payload: jsonb('payload').notNull(),
    imported_at: timestamp('imported_at', { withTimezone: true }).defaultNow().notNull(),
  },
  (table) => [
    index('ix_legacy_archives_sha256').on(table.sha256),
  ],
).enableRLS()