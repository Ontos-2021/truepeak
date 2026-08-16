import logging
import os
import uuid
from functools import wraps

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from ..analysis import (
    PLATFORMS,
    AnalysisConfig,
    allowed_file,
    analyze_file,
    build_verdicts,
    compact_result,
    process_normalization,
)
from ..export import export_csv, export_pdf
from .ratelimit import RateLimiter

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


def _get_limiter():
    app = current_app._get_current_object()
    limiter = app.extensions.get("truepeak_limiter")
    if limiter is None:
        limiter = RateLimiter(
            app.config["RATE_LIMIT_MAX_CALLS"],
            app.config["RATE_LIMIT_PER_SECONDS"],
            enabled_getter=lambda: app.config["RATE_LIMIT_ENABLED"],
        )
        app.extensions["truepeak_limiter"] = limiter
    return limiter


def limited(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not _get_limiter().allow():
            return jsonify({"error": "Too many requests. Please wait."}), 429
        return func(*args, **kwargs)

    return wrapped


def _save_upload(file):
    original = secure_filename(file.filename) or "audio"
    filename = f"{uuid.uuid4().hex}_{original}"
    path = os.path.join(current_app.config["TEMP_DIR"], filename)
    os.makedirs(current_app.config["TEMP_DIR"], exist_ok=True)
    file.save(path)
    return path, original


def _delete(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Could not delete temp file %s", path)


def _analysis_config():
    return AnalysisConfig(
        max_duration_minutes=current_app.config["MAX_DURATION_MINUTES"],
        compute_spectrum=True,
        compute_waveform=True,
        compute_correlation=True,
    )


def _album_summary(results):
    valid = [r for r in results if not r.get("error")]
    lufs = [r["analysis"].get("loudness_integrated_lufs") for r in valid]
    tp = [r["analysis"].get("true_peak_dbtp") for r in valid]
    lra = [r["analysis"].get("lra_lu") for r in valid]
    lufs_ok = [v for v in lufs if v is not None]
    tp_ok = [v for v in tp if v is not None]
    lra_ok = [v for v in lra if v is not None]
    return {
        "track_count": len(valid),
        "error_count": len(results) - len(valid),
        "lufs_min": min(lufs_ok) if lufs_ok else None,
        "lufs_max": max(lufs_ok) if lufs_ok else None,
        "lufs_spread_lu": (
            max(lufs_ok) - min(lufs_ok) if lufs_ok and len(lufs_ok) > 1 else None
        ),
        "max_true_peak_dbtp": max(tp_ok) if tp_ok else None,
        "mean_lra_lu": (sum(lra_ok) / len(lra_ok)) if lra_ok else None,
        "tracks": [
            {
                "filename": r["filename"],
                "loudness_integrated_lufs": r["analysis"].get(
                    "loudness_integrated_lufs"
                ),
                "true_peak_dbtp": r["analysis"].get("true_peak_dbtp"),
                "lra_lu": r["analysis"].get("lra_lu"),
            }
            for r in valid
        ],
    }


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/health")
def health():
    return jsonify({"status": "ok", "version": current_app.config["VERSION"]})


@bp.route("/api/targets")
def targets_route():
    return jsonify({"platforms": PLATFORMS})


@bp.route("/analyze", methods=["POST"])
@limited
def analyze_route():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        files = request.files.getlist("file")
        if not files or files[0].filename == "":
            return jsonify({"error": "No selected file"}), 400
        for file in files:
            if not file or not allowed_file(file.filename):
                return jsonify({"error": f"Invalid file type: {file.filename}"}), 400

        saved = []
        try:
            for file in files:
                saved.append(_save_upload(file))
        except Exception:
            logger.exception("Error saving uploads")
            for path, _ in saved:
                _delete(path)
            return jsonify({"error": "Could not save uploaded files"}), 500

        results = []
        try:
            for path, display_name in saved:
                try:
                    result = analyze_file(path, _analysis_config())
                    compact = compact_result(result)
                    compact["filename"] = display_name
                    compact["verdicts"] = build_verdicts(compact["analysis"])
                    results.append(compact)
                except Exception as exc:
                    logger.exception("Error analyzing %s", path)
                    results.append({
                        "filename": display_name,
                        "error": str(exc),
                    })
            album = _album_summary(results)
            return jsonify({"results": results, "album": album}), 200
        finally:
            for path, _ in saved:
                _delete(path)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error in /analyze")
        return jsonify({"error": "An unexpected error occurred. Please try again."}), 500


@bp.route("/export/pdf", methods=["POST"])
@limited
def export_pdf_route():
    try:
        payload = request.get_json(silent=True) or {}
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return jsonify({"error": "Invalid export data"}), 400
        album = payload.get("album")
        pdf_buffer = export_pdf(results, album)
        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name="truepeak_report.pdf",
        )
    except Exception:
        logger.exception("Error generating PDF")
        return jsonify({"error": "Error generating PDF"}), 500


@bp.route("/export/csv", methods=["POST"])
@limited
def export_csv_route():
    try:
        payload = request.get_json(silent=True) or {}
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            return jsonify({"error": "Invalid export data"}), 400
        csv_buffer = export_csv(results)
        return send_file(
            csv_buffer,
            mimetype="text/csv",
            as_attachment=True,
            download_name="truepeak_analysis.csv",
        )
    except Exception:
        logger.exception("Error generating CSV")
        return jsonify({"error": "Error generating CSV"}), 500


@bp.route("/normalize", methods=["POST"])
@limited
def normalize_route():
    app = current_app
    path = None
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        file = request.files["file"]
        if not file or file.filename == "":
            return jsonify({"error": "No selected file"}), 400
        if not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type"}), 400

        try:
            target = float(request.form.get("target_lufs", -14.0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid target loudness"}), 400
        if not (-40.0 <= target <= -5.0):
            return jsonify({"error": "Target loudness out of range"}), 400
        try:
            ceiling = float(request.form.get("max_tp_dbtp", -1.0))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid true peak ceiling"}), 400
        if not (-6.0 <= ceiling <= 0.0):
            return jsonify({"error": "True peak ceiling out of range"}), 400
        use_limiter = request.form.get("use_limiter", "1") not in ("0", "false")

        path, display_name = _save_upload(file)
        config = type(
            "NormalizeConfig",
            (),
            {
                "max_duration_minutes": app.config["MAX_NORMALIZE_DURATION_MINUTES"],
                "temp_dir": app.config["TEMP_DIR"],
            },
        )()
        result = process_normalization(path, target, ceiling, use_limiter, config)
        out_path = result.pop("out_path")
        token = app.config["TOKEN_STORE"].add(out_path)
        result["download_url"] = f"/normalize/download/{token}"
        result["filename"] = display_name
        return jsonify(result), 200
    except ValueError as exc:
        logger.warning("Normalization rejected: %s", exc)
        return jsonify({"error": str(exc)}), 400
    except Exception:
        logger.exception("Unexpected error in /normalize")
        return jsonify({"error": "An unexpected error occurred. Please try again."}), 500
    finally:
        _delete(path)


@bp.route("/normalize/download/<token>")
def normalize_download(token):
    path = current_app.config["TOKEN_STORE"].take(token)
    if path is None:
        return jsonify({"error": "Download expired or invalid"}), 404
    return send_file(
        path,
        mimetype="audio/wav",
        as_attachment=True,
        download_name="normalized_master.wav",
        max_age=0,
    )
