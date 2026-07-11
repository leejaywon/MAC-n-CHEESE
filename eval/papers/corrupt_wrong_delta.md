# Frozen Track 1 Paper: corrupt_wrong_delta

## Research Spec

- Falsifiable hypothesis: the candidate lowers `val_bpb`.
- Baseline: unchanged recipe with the same metric and seed 42.

## Short Paper

### Abstract

We compare one candidate with the frozen baseline.

### Experiments and Results

| Trial | Status | val_bpb |
|:------|:------:|--------------:|
| baseline | keep | 1.224 |
| candidate-1 | keep | 1.196 |

The absolute delta is -0.018.

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
