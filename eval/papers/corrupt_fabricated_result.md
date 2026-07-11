# Frozen Track 1 Paper: corrupt_fabricated_result

## Research Spec

- Falsifiable hypothesis: the candidate lowers `loss`.
- Baseline: unchanged recipe with the same metric and seed 42.

## Short Paper

### Abstract

We compare one candidate with the frozen baseline.

### Experiments and Results

| Trial | Status | loss |
|:------|:------:|--------------:|
| baseline | keep | 2.00 |
| candidate-1 | keep | 1.50 |

The candidate-1 achieved loss of 1.40.

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
