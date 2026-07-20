"""Launch the local-only Streamlit review application."""

import argparse
from pathlib import Path

from src.paths import REPO_ROOT
from src.review_app import ReviewStore, run_streamlit_app


def main() -> None:
    """Render generated candidates, blinded inputs, and ignored review output storage."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=REPO_ROOT / "data/outputs/scenario_generation/v0.5.1")
    parser.add_argument("--scoring-input-root", type=Path, default=REPO_ROOT / "data/outputs/review/evaluation_scoring_inputs")
    parser.add_argument(
        "--annotation-sample-manifest",
        type=Path,
        default=REPO_ROOT / "data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json",
    )
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "data/outputs/review/records")
    args = parser.parse_args()
    store = ReviewStore(
        candidate_root=args.candidate_root,
        scoring_input_root=args.scoring_input_root,
        output_root=args.output_root,
        annotation_sample_manifest_path=args.annotation_sample_manifest,
    )
    run_streamlit_app(store)


if __name__ == "__main__":
    main()
