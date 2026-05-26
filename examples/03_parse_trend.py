"""Demonstrate parsing an OLGA .tpl (trend / time-series) output file.

Loads the synthetic sample.tpl with `parse_tpl` and prints a summary
of the returned TrendData: OLGA version, time array shape, list of
variables, and the min/max of one variable. Each variable is a
VariableSeries whose .values is a 1D NumPy array of length
len(time).

The .tpl format itself is a custom OLGA text layout (header +
CATALOG + columnar TIME SERIES); the parser walks it once and
hands back typed objects.

Run from project root:
    python examples/03_parse_trend.py
"""

from __future__ import annotations

from pathlib import Path

from olga_automation.output_parser.tpl_parser import parse_tpl


SAMPLE = Path(__file__).parent / "sample.tpl"


def main() -> None:
    trend = parse_tpl(SAMPLE)

    print(f"File:         {SAMPLE.name}")
    print(f"OLGA version: {trend.olga_version}")
    print(f"Time unit:    {trend.time_unit}")
    print(f"Time array:   shape={trend.time.shape}  "
          f"first={trend.time[0]:.3f}  last={trend.time[-1]:.3f}")
    print()

    print(f"{'Variable key':<24} {'Name':<10} {'Position':<12} {'Unit':<8} "
          f"{'min':>14} {'max':>14}")
    print("-" * 90)
    for key, series in trend.variables.items():
        v = series.values
        print(f"{key:<24} {series.name:<10} {series.position:<12} "
              f"{series.unit:<8} {v.min():>14.6e} {v.max():>14.6e}")

    # Pick the first variable and show its first/last sample explicitly,
    # so the reader sees how to slice the underlying NumPy array.
    if trend.variables:
        first_key = next(iter(trend.variables))
        s = trend.variables[first_key]
        print()
        print(f"Sample slice of '{first_key}':")
        print(f"  t={trend.time[0]:.3f} {trend.time_unit}  value={s.values[0]:.6e} {s.unit}")
        print(f"  t={trend.time[-1]:.3f} {trend.time_unit}  value={s.values[-1]:.6e} {s.unit}")


if __name__ == "__main__":
    main()
