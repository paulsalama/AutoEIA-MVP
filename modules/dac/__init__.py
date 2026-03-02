"""
AutoEIA Module: Disadvantaged Communities Assessment
CEQR Technical Manual Chapter 23 — Effects on Disadvantaged Communities

Implements screening-level assessment per the Environmental Justice Siting Law (EJSL):
- Determines if project is within or within ½ mile of a DAC census tract
- Retrieves burden and vulnerability indicators for affected tracts
- Screens potential pollution burden relevance against CEQR technical areas
- Generates EAF-ready responses and narrative screening report

Legislative basis:
    - NYS Climate Leadership and Community Protection Act (2019)
    - Environmental Justice Siting Law (Ch. 840, 2022; amended Ch. 49, 2023)
    - Proposed Amendments to 6 NYCRR Part 617 (effective Dec 30, 2024)
"""

from .dac_assessment import DACAssessment
from .dac_data_loader import DACDataLoader
from .burden_analyzer import BurdenAnalyzer
from .report_generator import DACReportGenerator

__all__ = [
    "DACAssessment",
    "DACDataLoader",
    "BurdenAnalyzer",
    "DACReportGenerator",
]

__version__ = "1.0.0"
__ceqr_chapter__ = 23
