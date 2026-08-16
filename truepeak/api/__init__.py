import logging
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .. import __version__
from ..config import BASE_DIR, Config
from . import routes
from .tokens import TokenStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(config_overrides=None):
    cfg = Config()
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates"),
    )
    app.config.from_mapping({
        "VERSION": __version__,
        "TEMP_DIR": str(cfg.TEMP_DIR),
        "MAX_CONTENT_LENGTH": cfg.MAX_CONTENT_LENGTH,
        "RATE_LIMIT_ENABLED": cfg.RATE_LIMIT_ENABLED,
        "RATE_LIMIT_MAX_CALLS": cfg.RATE_LIMIT_MAX_CALLS,
        "RATE_LIMIT_PER_SECONDS": cfg.RATE_LIMIT_PER_SECONDS,
        "MAX_DURATION_MINUTES": cfg.MAX_DURATION_MINUTES,
        "MAX_NORMALIZE_DURATION_MINUTES": cfg.MAX_NORMALIZE_DURATION_MINUTES,
        "BRAND_NAME": cfg.BRAND_NAME,
        "BRAND_LOGO": cfg.BRAND_LOGO,
        "TOKEN_STORE": None,
        # Local tool: always serve fresh assets so the UI never goes stale.
        "SEND_FILE_MAX_AGE_DEFAULT": 0,
    })
    if config_overrides:
        app.config.update(config_overrides)

    os.makedirs(cfg.TEMP_DIR, exist_ok=True)
    app.config["TOKEN_STORE"] = TokenStore(
        str(cfg.TEMP_DIR), cfg.NORMALIZE_TOKEN_TTL_SECONDS
    )

    app.register_blueprint(routes.bp)

    @app.errorhandler(413)
    def file_too_large(error):
        return jsonify({"error": "File too large. Max upload size exceeded."}), 413

    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return error
        logger.exception("Unhandled exception")
        return jsonify({"error": "Server error. Please try again later."}), 500

    return app
