"""Download RCAEval benchmark cases from Hugging Face.

RCAEval (Pham et al., 2025, arXiv:2412.17015) contains failure cases injected
into real microservice systems, each labeled with its root-cause service.

Usage (from backend/):
    python -m scripts.download_rcaeval                    # RE2-OB, RE2-SS, RE3 (~1.3 GB)
    python -m scripts.download_rcaeval --suites re2tt     # any of re1ob, re2ss, re3tt, ...
"""
import argparse

from huggingface_hub import snapshot_download

from app.telemetry import DATA_DIR, DEFAULT_SUITES

def main():
    parser = argparse.ArgumentParser(description = __doc__)
    parser.add_argument("--suites", nargs = "+", default = DEFAULT_SUITES)
    args = parser.parse_args()

    patterns = ["cases.parquet"] + [f"{suite}_*/*" for suite in args.suites]
    snapshot_download(
        "phamquiluan/RCAEval",
        repo_type = "dataset",
        local_dir = DATA_DIR,
        allow_patterns = patterns,
        max_workers = 8,
    )
    print(f"Downloaded {', '.join(args.suites)} to {DATA_DIR}")

if __name__ == "__main__":
    main()
