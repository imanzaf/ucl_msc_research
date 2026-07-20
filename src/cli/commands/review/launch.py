"""Launch the local review dashboard through Streamlit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

from src.paths import REPO_ROOT


def _application_arguments(args: argparse.Namespace) -> List[str]:
    """Convert parsed review paths into arguments for the Streamlit application."""
    return [
        "--candidate-root",
        str(args.candidate_root),
        "--scoring-input-root",
        str(args.scoring_input_root),
        "--annotation-sample-manifest",
        str(args.annotation_sample_manifest),
        "--output-root",
        str(args.output_root),
    ]


def main() -> None:
    """Parse review storage paths and start a local-only Streamlit process."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-root", type=Path, default=REPO_ROOT / "data/outputs/scenario_generation/v0.5.1")
    parser.add_argument("--scoring-input-root", type=Path, default=REPO_ROOT / "data/outputs/review/evaluation_scoring_inputs")
    parser.add_argument(
        "--annotation-sample-manifest",
        type=Path,
        default=REPO_ROOT / "data/outputs/experiments/risk_comm_v1/checkpoints/evaluation_annotation_sample_manifest.json",
    )
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "data/outputs/review/records")
    parser.add_argument("--server-address", default="127.0.0.1")
    args = parser.parse_args()

    application_path = Path(__file__).with_name("app.py")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(application_path),
        "--server.address",
        args.server_address,
        "--",
        *_application_arguments(args),
    ]
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
