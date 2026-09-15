CREATE TABLE "audit_events" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"actor_id" varchar(64),
	"action" varchar(80) NOT NULL,
	"entity_type" varchar(60) NOT NULL,
	"entity_id" varchar(64) NOT NULL,
	"detail" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "audit_events" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "awards" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"student_id" varchar(64) NOT NULL,
	"experiment_version_id" varchar(64) NOT NULL,
	"score" integer NOT NULL,
	"awarded_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_awards_student_version" UNIQUE("student_id","experiment_version_id")
);

ALTER TABLE "awards" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "course_experiments" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"course_id" varchar(64) NOT NULL,
	"experiment_id" varchar(64) NOT NULL,
	"position" integer DEFAULT 0 NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_course_experiments_course_exp" UNIQUE("course_id","experiment_id")
);

ALTER TABLE "course_experiments" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "courses" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"teacher_id" varchar(64),
	"name" varchar(160) NOT NULL,
	"min_experiments_required" integer DEFAULT 3 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "courses" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "enrollments" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"course_id" varchar(64) NOT NULL,
	"student_id" varchar(64) NOT NULL,
	CONSTRAINT "uq_enrollments_course_student" UNIQUE("course_id","student_id")
);

ALTER TABLE "enrollments" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "evaluations" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"fingerprint" varchar(64) NOT NULL,
	"evaluator_version" varchar(40) NOT NULL,
	"model" varchar(120) DEFAULT 'deterministic-fallback' NOT NULL,
	"score" integer NOT NULL,
	"feedback" text NOT NULL,
	"result" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_evaluations_fingerprint_version" UNIQUE("fingerprint","evaluator_version")
);

ALTER TABLE "evaluations" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "experiment_drafts" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"teacher_id" varchar(64) NOT NULL,
	"experiment_id" varchar(64),
	"status" varchar(20) DEFAULT 'draft' NOT NULL,
	"code" varchar(24) NOT NULL,
	"title" varchar(160) NOT NULL,
	"definition" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"source_asset_hash" varchar(64),
	"source_kind" varchar(30) DEFAULT 'prompt' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "experiment_drafts" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "experiment_versions" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"experiment_id" varchar(64) NOT NULL,
	"version_no" integer DEFAULT 1 NOT NULL,
	"status" varchar(20) DEFAULT 'draft' NOT NULL,
	"definition" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"published_at" timestamp with time zone,
	CONSTRAINT "uq_experiment_versions_exp_version" UNIQUE("experiment_id","version_no")
);

ALTER TABLE "experiment_versions" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "experiments" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"code" varchar(24) NOT NULL,
	"title" varchar(160) NOT NULL,
	"order_no" integer DEFAULT 0 NOT NULL,
	"retired" boolean DEFAULT false NOT NULL
);

ALTER TABLE "experiments" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "file_assets" (
	"sha256" varchar(64) PRIMARY KEY NOT NULL,
	"object_key" varchar(200) NOT NULL,
	"original_name" varchar(240) NOT NULL,
	"content_type" varchar(120) NOT NULL,
	"size" integer NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "file_assets" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "legacy_archives" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"source_name" varchar(240) NOT NULL,
	"sha256" varchar(64) NOT NULL,
	"payload" jsonb NOT NULL,
	"imported_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "legacy_archives" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "quiz_assignments" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"course_id" varchar(64) NOT NULL,
	"student_id" varchar(64) NOT NULL,
	"experiment_version_id" varchar(64) NOT NULL,
	"questions" jsonb NOT NULL,
	"answers" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"attempt_no" integer DEFAULT 1 NOT NULL,
	"history" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"signature" varchar(64) NOT NULL,
	"frozen_at" timestamp with time zone DEFAULT now() NOT NULL,
	"completed_at" timestamp with time zone,
	CONSTRAINT "uq_quiz_course_version_signature" UNIQUE("course_id","experiment_version_id","signature"),
	CONSTRAINT "uq_quiz_course_student_version" UNIQUE("course_id","student_id","experiment_version_id")
);

ALTER TABLE "quiz_assignments" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "report_drafts" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"student_id" varchar(64) NOT NULL,
	"course_id" varchar(64) NOT NULL,
	"experiment_version_id" varchar(64) NOT NULL,
	"source_revision_id" varchar(64),
	"status" varchar(20) DEFAULT 'active' NOT NULL,
	"content" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"asset_hashes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"lock_version" integer DEFAULT 1 NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_report_drafts_course_student_version" UNIQUE("course_id","student_id","experiment_version_id")
);

ALTER TABLE "report_drafts" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "reviews" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"submission_id" varchar(64) NOT NULL,
	"teacher_id" varchar(64) NOT NULL,
	"private_score" integer NOT NULL,
	"private_comment" text DEFAULT '' NOT NULL,
	"decision" varchar(20) DEFAULT 'approved' NOT NULL,
	"superseded" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "reviews" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "student_experiment_progress" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"course_id" varchar(64) NOT NULL,
	"student_id" varchar(64) NOT NULL,
	"experiment_version_id" varchar(64) NOT NULL,
	"selected" boolean DEFAULT false NOT NULL,
	"completed_steps" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"step_data" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"asset_hashes" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"completed_at" timestamp with time zone,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "uq_student_progress_course_student_version" UNIQUE("course_id","student_id","experiment_version_id")
);

ALTER TABLE "student_experiment_progress" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "submission_revisions" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"request_id" varchar(80) NOT NULL,
	"student_id" varchar(64) NOT NULL,
	"course_id" varchar(64),
	"experiment_version_id" varchar(64) NOT NULL,
	"revision_no" integer NOT NULL,
	"status" varchar(24) DEFAULT 'submitted' NOT NULL,
	"payload" jsonb NOT NULL,
	"result_value" double precision NOT NULL,
	"relative_error" double precision NOT NULL,
	"deterministic_score" integer NOT NULL,
	"passed" boolean NOT NULL,
	"fingerprint" varchar(64) NOT NULL,
	"evaluation_id" varchar(64),
	"submitted_at" timestamp with time zone DEFAULT now() NOT NULL,
	"withdrawn_at" timestamp with time zone,
	"supersedes_id" varchar(64),
	CONSTRAINT "uq_submission_student_request" UNIQUE("student_id","request_id"),
	CONSTRAINT "uq_submission_course_student_version_revision" UNIQUE("course_id","student_id","experiment_version_id","revision_no")
);

ALTER TABLE "submission_revisions" ENABLE ROW LEVEL SECURITY;
CREATE TABLE "users" (
	"id" varchar(64) PRIMARY KEY NOT NULL,
	"username" varchar(80) NOT NULL,
	"name" varchar(120) NOT NULL,
	"role" varchar(20) NOT NULL,
	"password_hash" text NOT NULL,
	"active" boolean DEFAULT true NOT NULL,
	"must_change_password" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE "users" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "awards" ADD CONSTRAINT "awards_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "awards" ADD CONSTRAINT "awards_experiment_version_id_experiment_versions_id_fk" FOREIGN KEY ("experiment_version_id") REFERENCES "experiment_versions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "course_experiments" ADD CONSTRAINT "course_experiments_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "course_experiments" ADD CONSTRAINT "course_experiments_experiment_id_experiments_id_fk" FOREIGN KEY ("experiment_id") REFERENCES "experiments"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "courses" ADD CONSTRAINT "courses_teacher_id_users_id_fk" FOREIGN KEY ("teacher_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "enrollments" ADD CONSTRAINT "enrollments_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "enrollments" ADD CONSTRAINT "enrollments_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "experiment_drafts" ADD CONSTRAINT "experiment_drafts_teacher_id_users_id_fk" FOREIGN KEY ("teacher_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "experiment_drafts" ADD CONSTRAINT "experiment_drafts_experiment_id_experiments_id_fk" FOREIGN KEY ("experiment_id") REFERENCES "experiments"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "experiment_drafts" ADD CONSTRAINT "experiment_drafts_source_asset_hash_file_assets_sha256_fk" FOREIGN KEY ("source_asset_hash") REFERENCES "file_assets"("sha256") ON DELETE no action ON UPDATE no action;
ALTER TABLE "experiment_versions" ADD CONSTRAINT "experiment_versions_experiment_id_experiments_id_fk" FOREIGN KEY ("experiment_id") REFERENCES "experiments"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "quiz_assignments" ADD CONSTRAINT "quiz_assignments_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "quiz_assignments" ADD CONSTRAINT "quiz_assignments_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "quiz_assignments" ADD CONSTRAINT "quiz_assignments_experiment_version_id_experiment_versions_id_fk" FOREIGN KEY ("experiment_version_id") REFERENCES "experiment_versions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "report_drafts" ADD CONSTRAINT "report_drafts_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "report_drafts" ADD CONSTRAINT "report_drafts_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "report_drafts" ADD CONSTRAINT "report_drafts_experiment_version_id_experiment_versions_id_fk" FOREIGN KEY ("experiment_version_id") REFERENCES "experiment_versions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "report_drafts" ADD CONSTRAINT "report_drafts_source_revision_id_submission_revisions_id_fk" FOREIGN KEY ("source_revision_id") REFERENCES "submission_revisions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_submission_id_submission_revisions_id_fk" FOREIGN KEY ("submission_id") REFERENCES "submission_revisions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "reviews" ADD CONSTRAINT "reviews_teacher_id_users_id_fk" FOREIGN KEY ("teacher_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "student_experiment_progress" ADD CONSTRAINT "student_experiment_progress_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "student_experiment_progress" ADD CONSTRAINT "student_experiment_progress_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "student_experiment_progress" ADD CONSTRAINT "student_experiment_progress_experiment_version_id_experiment_versions_id_fk" FOREIGN KEY ("experiment_version_id") REFERENCES "experiment_versions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "submission_revisions" ADD CONSTRAINT "submission_revisions_student_id_users_id_fk" FOREIGN KEY ("student_id") REFERENCES "users"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "submission_revisions" ADD CONSTRAINT "submission_revisions_course_id_courses_id_fk" FOREIGN KEY ("course_id") REFERENCES "courses"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "submission_revisions" ADD CONSTRAINT "submission_revisions_experiment_version_id_experiment_versions_id_fk" FOREIGN KEY ("experiment_version_id") REFERENCES "experiment_versions"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "submission_revisions" ADD CONSTRAINT "submission_revisions_evaluation_id_evaluations_id_fk" FOREIGN KEY ("evaluation_id") REFERENCES "evaluations"("id") ON DELETE no action ON UPDATE no action;
ALTER TABLE "submission_revisions" ADD CONSTRAINT "submission_revisions_supersedes_id_submission_revisions_id_fk" FOREIGN KEY ("supersedes_id") REFERENCES "submission_revisions"("id") ON DELETE no action ON UPDATE no action;
CREATE INDEX "ix_audit_events_actor" ON "audit_events" USING btree ("actor_id");
CREATE INDEX "ix_audit_events_action" ON "audit_events" USING btree ("action");
CREATE INDEX "ix_awards_student" ON "awards" USING btree ("student_id");
CREATE INDEX "ix_awards_experiment_version" ON "awards" USING btree ("experiment_version_id");
CREATE INDEX "ix_course_experiments_course" ON "course_experiments" USING btree ("course_id");
CREATE INDEX "ix_course_experiments_experiment" ON "course_experiments" USING btree ("experiment_id");
CREATE INDEX "ix_courses_teacher_id" ON "courses" USING btree ("teacher_id");
CREATE INDEX "ix_enrollments_course" ON "enrollments" USING btree ("course_id");
CREATE INDEX "ix_enrollments_student" ON "enrollments" USING btree ("student_id");
CREATE INDEX "ix_evaluations_fingerprint" ON "evaluations" USING btree ("fingerprint");
CREATE INDEX "ix_experiment_drafts_teacher" ON "experiment_drafts" USING btree ("teacher_id");
CREATE INDEX "ix_experiment_drafts_experiment" ON "experiment_drafts" USING btree ("experiment_id");
CREATE INDEX "ix_experiment_drafts_status" ON "experiment_drafts" USING btree ("status");
CREATE INDEX "ix_experiment_versions_experiment" ON "experiment_versions" USING btree ("experiment_id");
CREATE INDEX "ix_experiment_versions_status" ON "experiment_versions" USING btree ("status");
CREATE UNIQUE INDEX "uq_experiments_code" ON "experiments" USING btree ("code");
CREATE UNIQUE INDEX "uq_file_assets_object_key" ON "file_assets" USING btree ("object_key");
CREATE INDEX "ix_legacy_archives_sha256" ON "legacy_archives" USING btree ("sha256");
CREATE INDEX "ix_quiz_student" ON "quiz_assignments" USING btree ("student_id");
CREATE INDEX "ix_quiz_experiment_version" ON "quiz_assignments" USING btree ("experiment_version_id");
CREATE INDEX "ix_report_drafts_student" ON "report_drafts" USING btree ("student_id");
CREATE INDEX "ix_report_drafts_source_revision" ON "report_drafts" USING btree ("source_revision_id");
CREATE INDEX "ix_report_drafts_status" ON "report_drafts" USING btree ("status");
CREATE INDEX "ix_reviews_submission" ON "reviews" USING btree ("submission_id");
CREATE INDEX "ix_reviews_teacher" ON "reviews" USING btree ("teacher_id");
CREATE INDEX "ix_reviews_decision" ON "reviews" USING btree ("decision");
CREATE INDEX "ix_student_progress_student" ON "student_experiment_progress" USING btree ("student_id");
CREATE INDEX "ix_student_progress_experiment_version" ON "student_experiment_progress" USING btree ("experiment_version_id");
CREATE INDEX "ix_submission_student" ON "submission_revisions" USING btree ("student_id");
CREATE INDEX "ix_submission_course" ON "submission_revisions" USING btree ("course_id");
CREATE INDEX "ix_submission_experiment_version" ON "submission_revisions" USING btree ("experiment_version_id");
CREATE INDEX "ix_submission_fingerprint" ON "submission_revisions" USING btree ("fingerprint");
CREATE UNIQUE INDEX "uq_users_username" ON "users" USING btree ("username");
CREATE INDEX "ix_users_role" ON "users" USING btree ("role");
-- === managed grants ===
REVOKE ALL ON TABLE audit_events FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE audit_events TO authenticated;

REVOKE ALL ON TABLE awards FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE awards TO authenticated;

REVOKE ALL ON TABLE course_experiments FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE course_experiments TO authenticated;

REVOKE ALL ON TABLE courses FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE courses TO authenticated;

REVOKE ALL ON TABLE enrollments FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE enrollments TO authenticated;

REVOKE ALL ON TABLE evaluations FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE evaluations TO authenticated;

REVOKE ALL ON TABLE experiment_drafts FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE experiment_drafts TO authenticated;

REVOKE ALL ON TABLE experiment_versions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE experiment_versions TO authenticated;

REVOKE ALL ON TABLE experiments FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE experiments TO authenticated;

REVOKE ALL ON TABLE file_assets FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE file_assets TO authenticated;

REVOKE ALL ON TABLE legacy_archives FROM anon, authenticated;
GRANT SELECT, INSERT ON TABLE legacy_archives TO authenticated;

REVOKE ALL ON TABLE quiz_assignments FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE quiz_assignments TO authenticated;

REVOKE ALL ON TABLE report_drafts FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE report_drafts TO authenticated;

REVOKE ALL ON TABLE reviews FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE reviews TO authenticated;

REVOKE ALL ON TABLE student_experiment_progress FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE student_experiment_progress TO authenticated;

REVOKE ALL ON TABLE submission_revisions FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE submission_revisions TO authenticated;

REVOKE ALL ON TABLE users FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE users TO authenticated;
