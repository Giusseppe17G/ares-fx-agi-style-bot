"""Strategy research layer."""

from .candidate_registry import CandidateRegistry
from .objective_functions import composite_score
from .overfit_guard import OverfitAssessment, assess_overfit
from .parameter_space import PARAMETER_SPACES, generate_research_parameter_sets, parameter_grid
from .regime_strategy_selector import RegimeSelection, select_for_regime
from .research_runner import run_research
from .strategy_candidate import StrategyCandidate
from .symbol_strategy_selector import build_symbol_strategy_mix

__all__ = [
    "CandidateRegistry",
    "OverfitAssessment",
    "PARAMETER_SPACES",
    "RegimeSelection",
    "StrategyCandidate",
    "assess_overfit",
    "build_symbol_strategy_mix",
    "composite_score",
    "generate_research_parameter_sets",
    "parameter_grid",
    "run_research",
    "select_for_regime",
]
