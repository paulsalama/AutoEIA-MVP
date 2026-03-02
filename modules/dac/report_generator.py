"""
DAC Report Generator
====================
Produces structured narrative reports for the Disadvantaged Communities
assessment, suitable for inclusion in:
  - Environmental Assessment Statements (EAS)
  - Environmental Impact Statements (EIS)
  - Determination of Significance narratives
  - Standalone screening memos

Report structure follows CEQR Technical Manual Chapter 23 methodology:
  1. Introduction and Regulatory Context
  2. Study Area Definition
  3. DAC Identification Results
  4. Existing Burden and Vulnerability Profile
  5. Pollution Burden Screening
  6. Determination
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class DACReportGenerator:
    """
    Generates narrative screening reports from DAC assessment results.

    Usage:
        generator = DACReportGenerator()
        markdown = generator.generate_screening_report(assessment_result)
        generator.save_report(markdown, "dac_screening_report.md")
    """

    def generate_screening_report(
        self,
        assessment_result: dict,
        project_name: str = "Proposed Action",
        applicant_name: str = "",
        ceqr_number: str = "",
        include_methodology: bool = True,
    ) -> str:
        """
        Generate a complete screening report in Markdown format.

        Args:
            assessment_result: Output from DACAssessment.run()
            project_name: Name of the proposed project
            applicant_name: Name of the applicant
            ceqr_number: CEQR application number if assigned
            include_methodology: Whether to include methodology section

        Returns:
            str: Markdown-formatted report
        """
        determination = assessment_result["screening_determination"]
        tracts = assessment_result["dac_tracts"]
        pollution = assessment_result["pollution_screening"]
        metadata = assessment_result.get("metadata", {})
        eaf = assessment_result.get("eaf_responses", {})

        sections = []

        # Header
        sections.append(self._header(project_name, ceqr_number, applicant_name))

        # Section 1: Introduction
        sections.append(self._introduction(determination))

        # Section 2: Regulatory Context
        if include_methodology:
            sections.append(self._regulatory_context())

        # Section 3: Study Area
        sections.append(self._study_area(metadata, determination))

        # Section 4: DAC Identification
        sections.append(self._dac_identification(determination, tracts))

        # Section 5: Burden Profile (if DACs found)
        if determination["dac_tracts_in_study_area"] > 0:
            sections.append(self._burden_profile(tracts))

        # Section 6: Pollution Screening
        if determination["dac_tracts_in_study_area"] > 0:
            sections.append(self._pollution_screening(pollution))

        # Section 7: Determination
        sections.append(self._determination(determination))

        # Section 8: EAF Responses
        sections.append(self._eaf_responses(eaf))

        return "\n\n".join(sections)

    def generate_summary(self, assessment_result: dict) -> str:
        """Generate a brief summary suitable for an EAS cover sheet."""
        det = assessment_result["screening_determination"]

        if det["proximity_classification"] == "outside_dac":
            return (
                "The proposed action is not located within or within ½ mile of a "
                "disadvantaged community as designated under the NYS Climate "
                "Leadership and Community Protection Act. No further assessment "
                "of effects on disadvantaged communities is warranted."
            )

        tracts = det["dac_tracts_in_study_area"]
        classification = det["proximity_classification"].replace("_", " ")

        summary = (
            f"The proposed action is {classification} to {tracts} disadvantaged "
            f"community census tract(s)."
        )

        if det["pollution_relevant_technical_areas"]:
            areas = ", ".join(det["pollution_relevant_technical_areas"])
            summary += (
                f" Potential pollution-relevant impacts have been identified in: "
                f"{areas}. Further assessment per CEQR Chapter 23 and the "
                f"Environmental Justice Siting Law is recommended."
            )
        else:
            summary += (
                " No pollution-relevant technical areas have been identified "
                "at this screening stage."
            )

        return summary

    @staticmethod
    def save_report(content: str, filepath: str):
        """Save report to file."""
        with open(filepath, "w") as f:
            f.write(content)
        logger.info(f"Report saved to {filepath}")

    @staticmethod
    def save_json(assessment_result: dict, filepath: str):
        """Save full assessment result as JSON."""
        # Remove geometry data for compact JSON output
        result_copy = json.loads(json.dumps(assessment_result, default=str))
        for tract in result_copy.get("dac_tracts", []):
            tract.pop("geometry", None)
        with open(filepath, "w") as f:
            json.dump(result_copy, f, indent=2, default=str)
        logger.info(f"JSON results saved to {filepath}")

    # ------------------------------------------------------------------
    # Report Sections
    # ------------------------------------------------------------------

    @staticmethod
    def _header(project_name: str, ceqr_number: str, applicant_name: str) -> str:
        lines = [f"# Effects on Disadvantaged Communities — Screening Assessment"]
        lines.append(f"## {project_name}")
        if ceqr_number:
            lines.append(f"**CEQR Number:** {ceqr_number}")
        if applicant_name:
            lines.append(f"**Applicant:** {applicant_name}")
        lines.append(
            f"**Assessment Date:** {datetime.now().strftime('%B %d, %Y')}"
        )
        lines.append(
            f"**CEQR Technical Manual Chapter:** 23 — Effects on Disadvantaged Communities (December 2025 Edition)"
        )
        return "\n\n".join(lines)

    @staticmethod
    def _introduction(determination: dict) -> str:
        classification = determination["proximity_classification"]
        if classification == "outside_dac":
            finding = (
                "the proposed action is **not located within or proximate to** "
                "a disadvantaged community"
            )
        elif classification == "within_dac":
            finding = (
                "the proposed action is **located within** a designated "
                "disadvantaged community"
            )
        elif classification == "proximate_to_dac":
            finding = (
                "the proposed action is **located within ½ mile of** a "
                "designated disadvantaged community"
            )
        else:
            finding = (
                "the proposed action is in **extended proximity** to a "
                "designated disadvantaged community"
            )

        return (
            "## 1. Introduction\n\n"
            "This assessment evaluates the potential effects of the proposed action "
            "on disadvantaged communities (DACs) as required by the Environmental "
            "Justice Siting Law (EJSL) and the CEQR Technical Manual Chapter 23 "
            "(December 2025 Edition). The EJSL, which took effect December 30, 2024, "
            "requires lead agencies to consider whether an action may cause or increase "
            "a disproportionate pollution burden on a DAC as part of the SEQRA process.\n\n"
            f"Based on this screening-level analysis, {finding}. "
            f"The assessment level required is: **{determination['assessment_level_required'].replace('_', ' ').title()}**."
        )

    @staticmethod
    def _regulatory_context() -> str:
        return (
            "## 2. Regulatory Context\n\n"
            "Under the NYS Climate Leadership and Community Protection Act (2019), "
            "the Climate Justice Working Group (CJWG) established criteria identifying "
            "approximately 35% of NYS census tracts as disadvantaged communities, "
            "using 45 indicators spanning environmental burdens, climate risks, health "
            "vulnerabilities, and socioeconomic characteristics.\n\n"
            "The Environmental Justice Siting Law (Chapter 840 of 2022, as amended by "
            "Chapter 49 of 2023) amends SEQRA (ECL Article 8) to require lead agencies "
            "to evaluate whether a proposed action may cause or increase a "
            "disproportionate pollution burden on a DAC — both in the determination of "
            "significance (ECL §8-0109) and in the preparation of an environmental "
            "impact statement (ECL §8-0113).\n\n"
            "DEC's proposed amendments to 6 NYCRR Part 617 implement these requirements "
            "through updated Environmental Assessment Forms that include DAC-specific "
            "screening questions. The DEC Disadvantaged Community Assessment Tool (DACAT) "
            "provides a methodology for evaluating disproportionality by comparing a "
            "subject DAC tract's burden and vulnerability scores to non-DAC aggregate "
            "denominators at statewide and regional scales."
        )

    @staticmethod
    def _study_area(metadata: dict, determination: dict) -> str:
        location = metadata.get("project_location", {})
        buffer = metadata.get("buffer_distance_miles", 0.5)

        return (
            "## 3. Study Area Definition\n\n"
            f"Per CEQR Technical Manual Chapter 23, Section 320, the study area for "
            f"the DAC assessment is defined as the area within **{buffer} miles** of "
            f"the project site.\n\n"
            f"**Project Location:** {location.get('lat', 'N/A')}°N, "
            f"{abs(location.get('lon', 0))}°W\n\n"
            f"**Study Area Radius:** {buffer} miles\n\n"
            f"**DAC Tracts in Study Area:** {determination['dac_tracts_in_study_area']}"
        )

    @staticmethod
    def _dac_identification(determination: dict, tracts: list) -> str:
        lines = ["## 4. DAC Identification Results\n"]

        if determination["dac_tracts_in_study_area"] == 0:
            lines.append(
                "No census tracts designated as disadvantaged communities under the "
                "NYS Climate Act were identified within the study area."
            )
            if determination.get("nearest_dac_geoid"):
                lines.append(
                    f"\nThe nearest DAC census tract ({determination['nearest_dac_geoid']}) "
                    f"is approximately {determination['nearest_dac_distance_miles']:.2f} "
                    f"miles from the project site."
                )
            return "\n".join(lines)

        lines.append(
            f"The following {determination['dac_tracts_in_study_area']} DAC census "
            f"tract(s) were identified within the study area:\n"
        )

        # Table header
        lines.append("| Census Tract (GEOID) | Distance (mi) | Relationship |")
        lines.append("|---|---|---|")

        for tract in tracts:
            if not tract.get("is_within_buffer", False):
                continue
            relationship = (
                "Project within tract"
                if tract.get("is_within_project", False)
                else "Within study area"
            )
            lines.append(
                f"| {tract['geoid']} | {tract['distance_miles']:.3f} | {relationship} |"
            )

        return "\n".join(lines)

    @staticmethod
    def _burden_profile(tracts: list) -> str:
        lines = ["## 5. Existing Burden and Vulnerability Profile\n"]

        tracts_in_buffer = [t for t in tracts if t.get("is_within_buffer", False)]

        for tract in tracts_in_buffer:
            lines.append(f"### Census Tract {tract['geoid']}\n")

            burden = tract.get("top_burden_indicators", [])
            vuln = tract.get("top_vulnerability_indicators", [])

            if burden:
                lines.append("**Elevated Environmental Burden Indicators:**\n")
                for name, pct in burden[:5]:
                    display_name = name.replace("_", " ").title()
                    lines.append(
                        f"- {display_name}: {pct:.0f}th percentile statewide"
                    )
                lines.append("")

            if vuln:
                lines.append("**Elevated Population Vulnerability Indicators:**\n")
                for name, pct in vuln[:5]:
                    display_name = name.replace("_", " ").title()
                    lines.append(
                        f"- {display_name}: {pct:.0f}th percentile statewide"
                    )
                lines.append("")

            if not burden and not vuln:
                lines.append(
                    "*Detailed indicator data not available at screening stage. "
                    "Refer to the CJWG DAC map for full indicator profiles.*\n"
                )

        return "\n".join(lines)

    @staticmethod
    def _pollution_screening(pollution: dict) -> str:
        lines = ["## 6. Pollution Burden Relevance Screening\n"]

        summary = pollution.get("_summary", {})
        high = summary.get("high_relevance_areas", [])
        moderate = summary.get("moderate_relevance_areas", [])

        if not high and not moderate:
            lines.append(
                "No CEQR technical areas with potential pollution relevance have "
                "been identified at this screening stage. If subsequent analysis "
                "identifies potential impacts in pollution-relevant technical areas "
                "(e.g., air quality, noise, hazardous materials), this DAC assessment "
                "should be revisited."
            )
            return "\n".join(lines)

        lines.append(
            "The following CEQR technical areas have been identified as potentially "
            "contributing to pollution burden in the affected DAC(s):\n"
        )

        if high:
            lines.append("**High Pollution Relevance:**\n")
            for area in high:
                display = area.replace("_", " ").title()
                lines.append(f"- {display}")
            lines.append("")

        if moderate:
            lines.append("**Moderate Pollution Relevance:**\n")
            for area in moderate:
                display = area.replace("_", " ").title()
                lines.append(f"- {display}")
            lines.append("")

        lines.append(
            "Per ECL §8-0109 and §8-0113, the lead agency must evaluate whether "
            "impacts in these technical areas may cause or increase a "
            "disproportionate pollution burden on the affected DAC(s). The DEC "
            "Disadvantaged Community Assessment Tool (DACAT) provides a methodology "
            "for this evaluation."
        )

        return "\n".join(lines)

    @staticmethod
    def _determination(determination: dict) -> str:
        lines = ["## 7. Screening Determination\n"]

        lines.append(f"**EAF Response — Within ½ mile of DAC:** "
                     f"{determination['eaf_question_within_half_mile']}\n")

        if determination["eaf_question_could_affect"] == "Yes":
            lines.append(f"**EAF Response — Could impacts affect DAC:** "
                        f"{determination['eaf_question_could_affect']}\n")

        lines.append(
            f"**Assessment Level Required:** "
            f"{determination['assessment_level_required'].replace('_', ' ').title()}\n"
        )

        lines.append(f"**Rationale:**\n\n{determination['rationale']}")

        return "\n".join(lines)

    @staticmethod
    def _eaf_responses(eaf: dict) -> str:
        lines = ["## 8. Environmental Assessment Form Responses\n"]

        lines.append(
            "The following responses are pre-populated for the DAC-related questions "
            "on the updated Environmental Assessment Forms (per proposed amendments "
            "to 6 NYCRR Part 617):\n"
        )

        short = eaf.get("short_eaf", {})
        full = eaf.get("full_eaf", {})

        lines.append("### Short EAF\n")
        for key, val in short.items():
            display_key = key.replace("_", " ").title()
            lines.append(f"- **{display_key}:** {val}")

        lines.append("\n### Full EAF\n")
        for key, val in full.items():
            display_key = key.replace("_", " ").title()
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val) if val else "None"
            lines.append(f"- **{display_key}:** {val}")

        notes = eaf.get("notes", "")
        if notes:
            lines.append(f"\n*{notes}*")

        return "\n".join(lines)
