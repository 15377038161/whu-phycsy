"use strict";
// Runtime entry for the platform's Node-based deploy image (nextjs-v3 profile).
//
// The platform runtime stage copies .next/standalone -> /app and launches
// `node server.js` as the non-root `node` user (UID 1000). The image has no
// system Python, so build.sh vendored a relocatable CPython at .python/ and
// pre-installed dependencies into vendor-py/. This wrapper starts the Flask app
// with that interpreter and forwards signals so the platform's lifecycle
// (SIGTERM on stop) reaches Python.
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const PY_DIR = path.join(ROOT, ".python");
const PY = path.join(PY_DIR, "bin", "python3");
const APP = path.join(ROOT, "app.py");
const VENDOR = path.join(ROOT, "vendor-py");

if (!fs.existsSync(PY)) {
  console.error("[runtime] FATAL: vendored python missing at " + PY);
  console.error("[runtime] build.sh must vendor .python/ into .next/standalone");
  process.exit(1);
}
if (!fs.existsSync(APP)) {
  console.error("[runtime] FATAL: app.py missing at " + APP);
  process.exit(1);
}

// Mirror scripts/start.sh: the deploy container has no PostgreSQL, so preview
// mode (SQLite) is the working default; explicit env always wins.
const env = Object.assign({}, process.env, {
  APP_ENV: process.env.APP_ENV || "preview",
  PYTHONUNBUFFERED: "1",
});

// Dependencies are pre-installed into vendor-py/ by build.sh.
const pythonPath = [VENDOR, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);
if (pythonPath) env.PYTHONPATH = pythonPath;

// Extension modules (.so) may link vendored shared libraries (fallback
// interpreter assembled from a system python).
const libDir = path.join(PY_DIR, "lib");
if (fs.existsSync(libDir)) {
  const ld = [libDir, process.env.LD_LIBRARY_PATH].filter(Boolean).join(path.delimiter);
  env.LD_LIBRARY_PATH = ld;
}

// The apt-copy fallback interpreter needs PYTHONHOME to locate its stdlib.
if (fs.existsSync(path.join(PY_DIR, ".needs-pythonhome"))) {
  env.PYTHONHOME = PY_DIR;
}

const port = env.DEPLOY_RUN_PORT || env.PORT || "5000";
console.log("[runtime] spawning flask app via " + PY + " on port " + port);
const child = spawn(PY, [APP], { stdio: "inherit", env });

const forward = (sig) => () => {
  try {
    child.kill(sig);
  } catch (_) {
    /* already gone */
  }
};
process.on("SIGTERM", forward("SIGTERM"));
process.on("SIGINT", forward("SIGINT"));

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code == null ? 1 : code);
});
