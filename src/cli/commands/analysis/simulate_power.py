"""Generate the frozen repeated-design, Holm-corrected power report offline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict

from src.analysis.power import VarianceComponents, expected_secondary_interval_half_widths, simulate_holm_corrected_power
from src.data_models.common import artifact_sha256, validate_model_self_hash
from src.data_models.manifests import FreezeStatus, PowerAssumptionManifest, PowerSimulationReport, PowerVarianceComponents, SmallestEffectManifest
from src.storage import read_model_json, write_model_json_atomic


def _components(values: PowerVarianceComponents, model_multiplier: float = 1.0, scoring_multiplier: float = 1.0) -> VarianceComponents:
    """Convert frozen Decimal components into simulation inputs with declared stress multipliers."""
    return VarianceComponents(
        pair_standard_deviation=float(values.pair_standard_deviation),
        fact_standard_deviation=float(values.fact_standard_deviation),
        scenario_standard_deviation=float(values.scenario_standard_deviation),
        model_standard_deviation=float(values.model_standard_deviation) * model_multiplier,
        scoring_error_standard_deviation=float(values.scoring_error_standard_deviation) * scoring_multiplier,
    )


def _simulate(
    effects: Dict[str, float],
    assumptions: PowerAssumptionManifest,
    simulations: int,
    alpha: float,
    seed: int,
    model_multiplier: float = 1.0,
    scoring_multiplier: float = 1.0,
) -> Dict[str, float]:
    """Run one base or stressed repeated-design power surface."""
    components = _components(assumptions.variance_components, model_multiplier, scoring_multiplier)
    return simulate_holm_corrected_power(effects, components, simulations, alpha, seed)


def main() -> None:
    """Validate frozen pre-evaluation assumptions and atomically persist power results."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--smallest-effect-manifest", type=Path, required=True)
    parser.add_argument("--power-assumption-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--simulations", type=int, default=5_000)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    smallest = read_model_json(args.smallest_effect_manifest, SmallestEffectManifest)
    assumptions = read_model_json(args.power_assumption_manifest, PowerAssumptionManifest)
    validate_model_self_hash(smallest, "manifest_sha256")
    validate_model_self_hash(assumptions, "manifest_sha256")
    if smallest.freeze_status != FreezeStatus.FROZEN or assumptions.freeze_status != FreezeStatus.FROZEN:
        raise ValueError("power simulation requires frozen smallest-effect and assumption manifests")
    if assumptions.smallest_effect_manifest_sha256 != smallest.manifest_sha256:
        raise ValueError("power assumptions do not bind the smallest-effect manifest")
    effects = {name: float(value) for name, value in smallest.absolute_bounds.items()}
    base = _simulate(effects, assumptions, args.simulations, args.alpha, args.seed)
    sensitivities = {
        "high_model_heterogeneity": _simulate(effects, assumptions, args.simulations, args.alpha, args.seed + 100, model_multiplier=1.5),
        "high_scoring_error": _simulate(effects, assumptions, args.simulations, args.alpha, args.seed + 200, scoring_multiplier=1.5),
    }
    secondary_precision = expected_secondary_interval_half_widths(
        {name: float(value) for name, value in assumptions.secondary_contrast_standard_deviations.items()}
    )
    payload = {
        "schema_version": "3.0.0",
        "power_assumption_manifest_sha256": assumptions.manifest_sha256,
        "smallest_effect_manifest_sha256": smallest.manifest_sha256,
        "simulations": args.simulations,
        "alpha": Decimal(str(args.alpha)),
        "random_seed": args.seed,
        "power": {name: Decimal(str(value)) for name, value in base.items()},
        "sensitivity_power": {
            sensitivity: {name: Decimal(str(value)) for name, value in values.items()} for sensitivity, values in sensitivities.items()
        },
        "secondary_expected_95_interval_half_widths": {name: Decimal(str(value)) for name, value in secondary_precision.items()},
        "generated_at": datetime.now(timezone.utc),
    }
    report = PowerSimulationReport.model_validate({**payload, "report_sha256": artifact_sha256(payload)})
    write_model_json_atomic(args.output, report)
    print(f"Wrote Holm-corrected repeated-design power report to {args.output}")


if __name__ == "__main__":
    main()
