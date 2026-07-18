"""Assessment profile loading and environment substitution."""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aica.evidence.manifest import CadCostBreakdown

VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


class AssessmentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    trigger: Literal["manual", "scheduled", "change", "retest", "fixture"]
    scope: tuple[str, ...]
    collectors: tuple[str, ...]
    objective_path: Path
    system_record_path: Path = Path("config/system-record.json")
    fixture_dir: Path | None = None
    observation_window_hours: int = Field(default=24, ge=1, le=24 * 31)
    estimated_cost_cad: float = Field(default=0, ge=0)
    cost_breakdown: CadCostBreakdown = Field(
        default_factory=lambda: CadCostBreakdown(
            model_estimate_cad=0,
            compute_estimate_cad=0,
            storage_estimate_cad=0,
            telemetry_estimate_cad=0,
            total_estimate_cad=0,
        )
    )

    @model_validator(mode="after")
    def total_matches_cost_breakdown(self) -> AssessmentProfile:
        if Decimal(str(self.estimated_cost_cad)) != Decimal(
            str(self.cost_breakdown.total_estimate_cad)
        ):
            raise ValueError("estimated_cost_cad must equal cost_breakdown.total_estimate_cad")
        return self


def _substitute(value: str) -> str:
    def replacement(match: re.Match[str]) -> str:
        name = match.group(1)
        resolved = os.environ.get(name) or os.environ.get(f"AICA_{name}")
        if not resolved:
            raise ValueError(f"assessment profile requires environment variable {name}")
        return resolved

    return VARIABLE.sub(replacement, value)


def load_profile(name_or_path: str, *, allow_unresolved: bool = False) -> AssessmentProfile:
    candidate = Path(name_or_path)
    if not candidate.is_file():
        candidate = Path("config/profiles") / f"{name_or_path}.json"
    raw = json.loads(candidate.read_text(encoding="utf-8"))
    try:
        raw["scope"] = [_substitute(item) for item in raw["scope"]]
    except ValueError:
        if not allow_unresolved:
            raise
    return AssessmentProfile.model_validate(raw)
