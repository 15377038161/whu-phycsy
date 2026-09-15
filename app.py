"""Gunicorn and local development entrypoint."""

import os

from platform_app import create_app

app = create_app()

if __name__ == "__main__":
    # Deployment platforms bind the app through DEPLOY_RUN_PORT/PORT (never hard-code 5000).
    port = int(os.getenv("DEPLOY_RUN_PORT") or os.getenv("PORT") or "5000")
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG"], threaded=True)
