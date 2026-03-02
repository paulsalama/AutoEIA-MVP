"""
DAC Assessment API Endpoint
============================
Flask blueprint for the DAC assessment module.
Integrates with the AutoEIA platform backend (platform/backend/app.py).

Endpoints:
    POST /api/modules/dac_assessment/run        — Execute full screening
    POST /api/modules/dac_assessment/burden      — Run Tier 2 burden analysis
    GET  /api/modules/dac_assessment/check       — Quick proximity check
    GET  /api/modules/dac_assessment/indicators   — Get indicator definitions
"""

from flask import Blueprint, request, jsonify
import logging
import traceback

logger = logging.getLogger(__name__)

dac_blueprint = Blueprint("dac_assessment", __name__, url_prefix="/api/modules/dac_assessment")


def _get_assessment():
    """Lazy-load the assessment module."""
    from .dac_assessment import DACAssessment
    from .dac_data_loader import DACDataLoader
    loader = DACDataLoader()
    return DACAssessment(data_loader=loader)


def _get_burden_analyzer():
    """Lazy-load the burden analyzer."""
    from .burden_analyzer import BurdenAnalyzer
    return BurdenAnalyzer()


def _get_report_generator():
    """Lazy-load the report generator."""
    from .report_generator import DACReportGenerator
    return DACReportGenerator()


# ---------------------------------------------------------------------------
# POST /run — Full screening assessment
# ---------------------------------------------------------------------------

@dac_blueprint.route("/run", methods=["POST"])
def run_assessment():
    """
    Execute the full CEQR Chapter 23 DAC screening assessment.

    Request body:
    {
        "project_location": [40.6782, -73.9442],   // [lat, lon] — required
        "project_polygon": null,                     // GeoJSON polygon — optional
        "project_description": "Mixed-use dev...",   // optional
        "ceqr_technical_areas": ["air_quality", "noise"],  // optional
        "buffer_distance_miles": 0.5,                // optional, default 0.5
        "project_name": "123 Main Street",           // for report — optional
        "ceqr_number": "24-XXX",                     // for report — optional
        "generate_report": true                      // optional, default true
    }

    Returns:
    {
        "success": true,
        "result": { ... screening results ... },
        "report_markdown": "# Effects on Disadvantaged...",
        "summary": "The proposed action is..."
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "Request body required"}), 400

        # Validate required fields
        location = data.get("project_location")
        if not location or len(location) != 2:
            return jsonify({
                "success": False,
                "error": "project_location required as [lat, lon] array",
            }), 400

        lat, lon = float(location[0]), float(location[1])

        # Validate coordinates are roughly in NYC area
        if not (40.4 <= lat <= 41.0 and -74.3 <= lon <= -73.6):
            logger.warning(
                f"Coordinates ({lat}, {lon}) are outside typical NYC bounds. "
                f"Proceeding anyway — may return no results."
            )

        # Run assessment
        assessment = _get_assessment()
        result = assessment.run(
            project_location=(lat, lon),
            project_polygon=data.get("project_polygon"),
            project_description=data.get("project_description", ""),
            ceqr_technical_areas=data.get("ceqr_technical_areas"),
            buffer_distance_miles=data.get("buffer_distance_miles", 0.5),
        )

        # Generate report if requested
        report_md = None
        summary = None
        if data.get("generate_report", True):
            generator = _get_report_generator()
            report_md = generator.generate_screening_report(
                result,
                project_name=data.get("project_name", "Proposed Action"),
                ceqr_number=data.get("ceqr_number", ""),
                applicant_name=data.get("applicant_name", ""),
            )
            summary = generator.generate_summary(result)

        # Strip geometry from JSON response (too large for API)
        for tract in result.get("dac_tracts", []):
            tract.pop("geometry", None)

        return jsonify({
            "success": True,
            "result": result,
            "report_markdown": report_md,
            "summary": summary,
        })

    except FileNotFoundError as e:
        return jsonify({
            "success": False,
            "error": f"Data not found: {str(e)}. Run fetch_data first.",
        }), 404

    except Exception as e:
        logger.error(f"DAC assessment error: {traceback.format_exc()}")
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


# ---------------------------------------------------------------------------
# POST /burden — Tier 2 burden analysis
# ---------------------------------------------------------------------------

@dac_blueprint.route("/burden", methods=["POST"])
def run_burden_analysis():
    """
    Execute Tier 2 DACAT-style disproportionality analysis.

    Request body:
    {
        "tracts": [
            {
                "geoid": "36047014600",
                "indicators": {
                    "pm25_concentration": 82.3,
                    "asthma_ed_visits": 91.2,
                    ...
                }
            }
        ],
        "urban_rural": "urban",
        "region": "nyc"
    }
    """
    try:
        data = request.get_json()
        if not data or "tracts" not in data:
            return jsonify({
                "success": False,
                "error": "Request body with 'tracts' array required",
            }), 400

        analyzer = _get_burden_analyzer()
        result = analyzer.analyze_multiple_tracts(
            tracts_data=data["tracts"],
            urban_rural=data.get("urban_rural", "urban"),
            region=data.get("region", "nyc"),
        )

        return jsonify({"success": True, "result": result})

    except Exception as e:
        logger.error(f"Burden analysis error: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /check — Quick proximity check
# ---------------------------------------------------------------------------

@dac_blueprint.route("/check", methods=["GET"])
def quick_check():
    """
    Quick check: is a location within or near a DAC?

    Query params:
        lat: float — latitude
        lon: float — longitude
        buffer: float — buffer distance in miles (default 0.5)

    Returns:
    {
        "within_dac": false,
        "within_buffer": true,
        "nearest_dac_geoid": "36047014600",
        "nearest_dac_distance_miles": 0.234,
        "dac_count_in_buffer": 3
    }
    """
    try:
        lat = request.args.get("lat", type=float)
        lon = request.args.get("lon", type=float)
        buffer_miles = request.args.get("buffer", default=0.5, type=float)

        if lat is None or lon is None:
            return jsonify({
                "success": False,
                "error": "lat and lon query parameters required",
            }), 400

        assessment = _get_assessment()
        result = assessment.run(
            project_location=(lat, lon),
            buffer_distance_miles=buffer_miles,
        )

        det = result["screening_determination"]
        return jsonify({
            "success": True,
            "within_dac": det["project_within_dac"],
            "within_buffer": det["project_within_half_mile_of_dac"],
            "proximity_classification": det["proximity_classification"],
            "nearest_dac_geoid": det["nearest_dac_geoid"],
            "nearest_dac_distance_miles": det["nearest_dac_distance_miles"],
            "dac_count_in_buffer": det["dac_tracts_in_study_area"],
        })

    except Exception as e:
        logger.error(f"Quick check error: {traceback.format_exc()}")
        return jsonify({"success": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# GET /indicators — Indicator definitions
# ---------------------------------------------------------------------------

@dac_blueprint.route("/indicators", methods=["GET"])
def get_indicators():
    """
    Return the list of 45 DAC indicators grouped by factor.
    """
    from .dac_data_loader import DACDataLoader
    return jsonify({
        "success": True,
        "indicator_factors": DACDataLoader.get_indicator_factors(),
        "all_indicators": DACDataLoader.get_all_indicators(),
        "total_count": len(DACDataLoader.get_all_indicators()),
    })
