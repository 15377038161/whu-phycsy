import { defineConfig } from 'drizzle-kit'

export default defineConfig({
  schema: './src/schema.ts',
  out: './drizzle',
  dialect: 'postgresql',
  dbCredentials: {
    // Placeholder only — `drizzle-kit generate` never connects to the database.
    url: 'postgresql://placeholder:placeholder@localhost:5432/postgres',
  },
})