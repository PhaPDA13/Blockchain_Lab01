"""
Single entry point to execute all unit and end-to-end tests for Lab 01.
Usage:
    python -m tests.run_all_tests
or:
    python tests/run_all_tests.py
"""
import sys
# pyrefly: ignore[missing-import]
import pytest


def main():
    print("=" * 70)
    print("Blockchain Lab 01 - Running All Unit and End-to-End Tests")
    print("=" * 70)

    # Run pytest on tests directory
    args = ["-v", "tests/"]
    exit_code = pytest.main(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
