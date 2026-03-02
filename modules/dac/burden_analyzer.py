"""
Burden Analyzer — DACAT Disproportionality Methodology
=======================================================
Implements the DEC Disadvantaged Community Assessment Tool (DACAT) logic
for evaluating whether a project's impacts would create or increase a
disproportionate pollution burden on a DAC.

The DACAT methodology (per DEC's Regulatory Impact Statement, Appendix A):

  1. Identify the subject DAC census tract(s)
  2. Classify each tract as urban or rural (per Census designation)
  3. Determine the applicable region (NYC, Rest of State, or specific Regional Council)
  4. Calculate three component scores:
     - Combined Score
     - Burden Component Score (environmental burdens + climate risks + land use)
     - Vulnerability Component Score (health + housing + income + race)
  5. Compare each component to the aggregate denominator:
     - The aggregate denominator is the LOWEST of the statewide and regional
       non-DAC means for the applicable urban/rural classification
     - This maximizes protection by selecting the most protective comparator
  6. Calculate the percentage delta: ((DAC score - aggregate) / aggregate) × 100
  7. A tract is considered to have disproportionate burden if its score
     exceeds the aggregate denominator by ≥25%

This is the Tier 2 analysis. Tier 1 (screening) is handled by dac_assessment.py.
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from .dac_data_loader import DACDataLoader, DAC_INDICATOR_FACTORS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DACAT Reference Values
# ---------------------------------------------------------------------------
# These are approximate aggregate denominators derived from the DACAT methodology.
# In production, these should be loaded from DEC's published reference data.
# The structure is: {classification: {region: {component: mean_value}}}

AGGREGATE_DENOMINATORS = {
    "urban": {
        "statewide": {
            "combined_score": 55.20,
            "burden_component": 52.80,
            "vulnerability_component": 57.10,
        },
        "nyc": {
            "combined_score": 58.40,
            "burden_component": 56.20,
            "vulnerability_component": 59.30,
        },
    },
    "rural": {
        "statewide": {
            "combined_score": 63.05,
            "burden_component": 61.40,
            "vulnerability_component": 64.20,
        },
    },
}

# Threshold for disproportionality determination
DISPROPORTIONALITY_THRESHOLD_PCT = 25.0


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class IndicatorScore:
    """Score detail for a single indicator."""
    indicator: str
    factor: str
    percentile: float
    statewide_rank_description: str = ""  # e.g., "higher than 85% of tracts statewide"


@dataclass
class ComponentScore:
    """Calculated component score and disproportionality comparison."""
    component_name: str  # combined, burden, or vulnerability
    tract_score: float
    aggregate_denominator: float
    aggregate_source: str  # e.g., "Statewide Urban Mean"
    delta_pct: float  # percentage above/below aggregate
    is_disproportionate: bool  # delta_pct >= 25%
    constituent_indicators: list = field(default_factory=list)


@dataclass
class BurdenAnalysisResult:
    """Full burden analysis result for a single DAC tract."""
    geoid: str
    urban_rural_classification: str
    region: str
    combined_score: Optional[ComponentScore] = None
    burden_component: Optional[ComponentScore] = None
    vulnerability_component: Optional[ComponentScore] = None
    overall_disproportionate: bool = False
    disproportionality_type: str = ""  # "burden", "vulnerability", "both", "none"
    high_burden_indicators: list = field(default_factory=list)
    high_vulnerability_indicators: list = field(default_factory=list)
    narrative: str = ""


class BurdenAnalyzer:
    """
    Performs Tier 2 burden disproportionality analysis using the DACAT methodology.

    Usage:
        analyzer = BurdenAnalyzer()
        result = analyzer.analyze_tract(
            geoid="36047014600",
            indicators={"pm25_concentration": 82.3, "asthma_ed_visits": 91.2, ...},
            urban_rural="urban",
            region="nyc",
        )
    """

    def __init__(
        self,
        aggregate_denominators: Optional[dict] = None,
        disproportionality_threshold: float = DISPROPORTIONALITY_THRESHOLD_PCT,
    ):
        self.denominators = aggregate_denominators or AGGREGATE_DENOMINATORS
        self.threshold = disproportionality_threshold

    def analyze_tract(
        self,
        geoid: str,
        indicators: dict,
        urban_rural: str = "urban",
        region: str = "nyc",
    ) -> BurdenAnalysisResult:
        """
        Run full DACAT-style disproportionality analysis for a single tract.

        Args:
            geoid: Census tract FIPS code
            indicators: {indicator_name: percentile_value} mapping
            urban_rural: "urban" or "rural"
            region: "nyc", "statewide", or specific regional council name

        Returns:
            BurdenAnalysisResult with component scores and determination
        """
        classification = urban_rural.lower()
        region_key = region.lower()

        # Split indicators into burden vs vulnerability
        burden_indicators, vulnerability_indicators = self._partition_indicators(
            indicators
        )

        # Calculate component scores (mean of constituent indicator percentiles)
        burden_score = self._calculate_component_mean(burden_indicators)
        vulnerability_score = self._calculate_component_mean(vulnerability_indicators)
        combined_score = self._calculate_component_mean(
            {**burden_indicators, **vulnerability_indicators}
        )

        # Get aggregate denominators (lowest of statewide and regional)
        combined_agg, combined_source = self._get_aggregate(
            classification, region_key, "combined_score"
        )
        burden_agg, burden_source = self._get_aggregate(
            classification, region_key, "burden_component"
        )
        vuln_agg, vuln_source = self._get_aggregate(
            classification, region_key, "vulnerability_component"
        )

        # Calculate deltas
        combined_component = self._build_component_score(
            "combined_score", combined_score, combined_agg, combined_source,
            {**burden_indicators, **vulnerability_indicators},
        )
        burden_component = self._build_component_score(
            "burden_component", burden_score, burden_agg, burden_source,
            burden_indicators,
        )
        vulnerability_component = self._build_component_score(
            "vulnerability_component", vulnerability_score, vuln_agg, vuln_source,
            vulnerability_indicators,
        )

        # Determine overall disproportionality
        burden_disprop = burden_component.is_disproportionate
        vuln_disprop = vulnerability_component.is_disproportionate
        overall = combined_component.is_disproportionate

        if burden_disprop and vuln_disprop:
            disprop_type = "both"
        elif burden_disprop:
            disprop_type = "burden"
        elif vuln_disprop:
            disprop_type = "vulnerability"
        else:
            disprop_type = "none"

        # Identify highest-scoring indicators
        high_burden = [
            IndicatorScore(
                indicator=name,
                factor=DACDataLoader.get_indicator_factor(name) or "unknown",
                percentile=pct,
                statewide_rank_description=(
                    f"higher than {pct:.0f}% of census tracts statewide"
                ),
            )
            for name, pct in sorted(
                burden_indicators.items(), key=lambda x: x[1], reverse=True
            )
            if pct >= 75.0
        ]

        high_vulnerability = [
            IndicatorScore(
                indicator=name,
                factor=DACDataLoader.get_indicator_factor(name) or "unknown",
                percentile=pct,
                statewide_rank_description=(
                    f"higher than {pct:.0f}% of census tracts statewide"
                ),
            )
            for name, pct in sorted(
                vulnerability_indicators.items(), key=lambda x: x[1], reverse=True
            )
            if pct >= 75.0
        ]

        # Build narrative
        narrative = self._build_narrative(
            geoid, classification, region_key,
            combined_component, burden_component, vulnerability_component,
            high_burden, high_vulnerability,
        )

        return BurdenAnalysisResult(
            geoid=geoid,
            urban_rural_classification=classification,
            region=region_key,
            combined_score=combined_component,
            burden_component=burden_component,
            vulnerability_component=vulnerability_component,
            overall_disproportionate=overall,
            disproportionality_type=disprop_type,
            high_burden_indicators=[asdict(i) for i in high_burden],
            high_vulnerability_indicators=[asdict(i) for i in high_vulnerability],
            narrative=narrative,
        )

    def analyze_multiple_tracts(
        self,
        tracts_data: list,
        urban_rural: str = "urban",
        region: str = "nyc",
    ) -> dict:
        """
        Analyze multiple DAC tracts and produce aggregate findings.

        Args:
            tracts_data: list of {"geoid": str, "indicators": dict}
            urban_rural: classification for all tracts
            region: region for all tracts

        Returns:
            dict with individual results and aggregate summary
        """
        results = []
        for tract in tracts_data:
            result = self.analyze_tract(
                geoid=tract["geoid"],
                indicators=tract["indicators"],
                urban_rural=urban_rural,
                region=region,
            )
            results.append(result)

        # Aggregate
        any_disproportionate = any(r.overall_disproportionate for r in results)
        disproportionate_tracts = [
            r.geoid for r in results if r.overall_disproportionate
        ]

        # Collect all high indicators across tracts
        all_high_burden = set()
        all_high_vuln = set()
        for r in results:
            for ind in r.high_burden_indicators:
                all_high_burden.add(ind["indicator"])
            for ind in r.high_vulnerability_indicators:
                all_high_vuln.add(ind["indicator"])

        return {
            "individual_results": [asdict(r) for r in results],
            "summary": {
                "total_tracts_analyzed": len(results),
                "tracts_with_disproportionate_burden": len(disproportionate_tracts),
                "disproportionate_tract_geoids": disproportionate_tracts,
                "any_disproportionate": any_disproportionate,
                "common_high_burden_indicators": sorted(all_high_burden),
                "common_high_vulnerability_indicators": sorted(all_high_vuln),
            },
        }

    # ------------------------------------------------------------------
    # Internal Methods
    # ------------------------------------------------------------------

    @staticmethod
    def _partition_indicators(indicators: dict) -> tuple:
        """Split indicators into burden and vulnerability categories."""
        burden_factors = {
            "potential_pollution_exposure",
            "potential_climate_change_risk",
            "land_use_historic_discrimination",
        }
        vulnerability_factors = {
            "health_impacts_burdens",
            "housing_mobility_communications",
            "income",
            "race_ethnicity",
        }

        burden = {}
        vulnerability = {}

        for name, value in indicators.items():
            if not isinstance(value, (int, float)):
                continue
            factor = DACDataLoader.get_indicator_factor(name)
            if factor in burden_factors:
                burden[name] = value
            elif factor in vulnerability_factors:
                vulnerability[name] = value

        return burden, vulnerability

    @staticmethod
    def _calculate_component_mean(indicators: dict) -> float:
        """Calculate mean percentile across a set of indicators."""
        values = [v for v in indicators.values() if isinstance(v, (int, float))]
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _get_aggregate(
        self, classification: str, region: str, component: str
    ) -> tuple:
        """
        Get the aggregate denominator for comparison.
        Per DACAT methodology: select the LOWEST of statewide and regional means.

        Returns (value, source_description)
        """
        statewide = (
            self.denominators.get(classification, {})
            .get("statewide", {})
            .get(component, 50.0)
        )
        regional = (
            self.denominators.get(classification, {})
            .get(region, {})
            .get(component)
        )

        if regional is not None and regional < statewide:
            return regional, f"{region.upper()} {classification.title()} Mean"
        return statewide, f"Statewide {classification.title()} Mean"

    def _build_component_score(
        self,
        name: str,
        score: float,
        aggregate: float,
        aggregate_source: str,
        indicators: dict,
    ) -> ComponentScore:
        """Build a ComponentScore with delta calculation."""
        if aggregate == 0:
            delta = 0.0
        else:
            delta = ((score - aggregate) / aggregate) * 100

        return ComponentScore(
            component_name=name,
            tract_score=round(score, 2),
            aggregate_denominator=round(aggregate, 2),
            aggregate_source=aggregate_source,
            delta_pct=round(delta, 2),
            is_disproportionate=delta >= self.threshold,
            constituent_indicators=[
                {"indicator": k, "percentile": round(v, 2)}
                for k, v in sorted(indicators.items(), key=lambda x: x[1], reverse=True)
            ],
        )

    def _build_narrative(
        self,
        geoid: str,
        classification: str,
        region: str,
        combined: ComponentScore,
        burden: ComponentScore,
        vulnerability: ComponentScore,
        high_burden: list,
        high_vulnerability: list,
    ) -> str:
        """Generate narrative analysis for a tract's burden assessment."""

        lines = [
            f"Census tract {geoid} is classified as {classification} and located "
            f"within the {region.upper()} region."
        ]

        # Combined score
        if combined.is_disproportionate:
            lines.append(
                f"The tract's combined score ({combined.tract_score:.1f}) exceeds "
                f"the {combined.aggregate_source} ({combined.aggregate_denominator:.1f}) "
                f"by {combined.delta_pct:+.1f}%, which is above the {self.threshold}% "
                f"disproportionality threshold."
            )
        else:
            lines.append(
                f"The tract's combined score ({combined.tract_score:.1f}) is "
                f"{combined.delta_pct:+.1f}% relative to the {combined.aggregate_source} "
                f"({combined.aggregate_denominator:.1f}), which is below the "
                f"{self.threshold}% disproportionality threshold."
            )

        # Burden component
        if burden.is_disproportionate:
            lines.append(
                f"The environmental burden component ({burden.tract_score:.1f}) "
                f"is disproportionately high ({burden.delta_pct:+.1f}% vs. "
                f"{burden.aggregate_source})."
            )
            if high_burden:
                top_names = [i.indicator.replace("_", " ") for i in high_burden[:3]]
                lines.append(
                    f"Key elevated burden indicators include: {', '.join(top_names)}."
                )

        # Vulnerability component
        if vulnerability.is_disproportionate:
            lines.append(
                f"The population vulnerability component "
                f"({vulnerability.tract_score:.1f}) is disproportionately high "
                f"({vulnerability.delta_pct:+.1f}% vs. "
                f"{vulnerability.aggregate_source})."
            )
            if high_vulnerability:
                top_names = [i.indicator.replace("_", " ") for i in high_vulnerability[:3]]
                lines.append(
                    f"Key elevated vulnerability indicators include: "
                    f"{', '.join(top_names)}."
                )

        return " ".join(lines)
