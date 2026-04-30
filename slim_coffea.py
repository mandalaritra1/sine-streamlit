from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import hist
from coffea.util import load, save


DEFAULT_HIST_KEY = "mtt_vs_dy_vs_chi"
REQUIRED_AXES = {"ttbarmass", "jetdy", "chi"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write slim coffea files containing only the ttbar 3D mtt/dy/chi histogram."
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="Input .coffea files")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for slim files. Defaults to each input file's directory.",
    )
    parser.add_argument(
        "--suffix",
        default="_mtt_dy_chi_only",
        help="Suffix appended before .coffea for output filenames.",
    )
    args = parser.parse_args()

    for input_path in args.inputs:
        output_path = output_name(input_path, args.output_dir, args.suffix)
        slim_file(input_path, output_path)
        print(f"Wrote {output_path}")


def output_name(input_path: Path, output_dir: Path | None, suffix: str) -> Path:
    directory = output_dir if output_dir is not None else input_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{input_path.stem}{suffix}.coffea"


def slim_file(input_path: Path, output_path: Path) -> None:
    output = load(input_path)
    hist_obj = find_3d_hist(output)
    save({DEFAULT_HIST_KEY: hist_obj}, output_path)


def find_3d_hist(output: Any) -> hist.Hist:
    if not isinstance(output, dict):
        raise TypeError(f"Expected a dict-like coffea output, got {type(output).__name__}")

    preferred = output.get(DEFAULT_HIST_KEY)
    if isinstance(preferred, hist.Hist) and has_required_axes(preferred):
        return preferred

    for value in output.values():
        if isinstance(value, hist.Hist) and has_required_axes(value):
            return value

    available = {
        str(key): [axis.name for axis in value.axes]
        for key, value in output.items()
        if isinstance(value, hist.Hist)
    }
    raise ValueError(f"No histogram with axes {sorted(REQUIRED_AXES)} found. Available: {available}")


def has_required_axes(hist_obj: hist.Hist) -> bool:
    return REQUIRED_AXES.issubset({axis.name for axis in hist_obj.axes})


if __name__ == "__main__":
    main()
