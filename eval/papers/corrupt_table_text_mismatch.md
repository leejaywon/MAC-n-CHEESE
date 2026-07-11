# Frozen Track 1 Paper: corrupt_table_text_mismatch

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
| candidate-1 | keep | 75.0 |

The candidate-1 achieved accuracy of 74.0.

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
