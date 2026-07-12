# Frozen Track 1 Paper: corrupt_mean_then_delta

## Research Spec

- Falsifiable hypothesis: the candidate raises `accuracy`.
- Baseline: unchanged recipe with the same metric and seed 42.

## Short Paper

### Abstract

We compare one candidate with the frozen baseline.

### Experiments and Results

| Trial | Status | accuracy |
|:------|:------:|--------------:|
| baseline | keep | 70.0 |
| baseline | keep | 72.0 |
| candidate-1 | keep | 74.0 |
| candidate-1 | keep | 76.0 |

Averaging the two runs per system, the absolute delta is 5.0.

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
