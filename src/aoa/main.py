"""Command-line entry point for AOA."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Optimization Automation")
    parser.parse_args()
    print("AOA is ready. Add an optimization workflow to get started.")


if __name__ == "__main__":
    main()
