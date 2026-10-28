-- Migration: Add avatar_url, phone, student_code to users table
-- These fields are populated from Chaoxing SSO metadata on login

ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "avatar_url" varchar(500);
ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "phone" varchar(40);
ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "student_code" varchar(80);
ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "chaoxing_cxid" varchar(64);

-- Index for chaoxing_cxid lookups during OAuth callback
CREATE INDEX IF NOT EXISTS "users_chaoxing_cxid_idx" ON "users" ("chaoxing_cxid");
