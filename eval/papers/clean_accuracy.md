# Frozen Track 1 Paper: clean_accuracy

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

The absolute delta is 5.0 and relative improvement is 7.14%.

### Limitations and Conclusion

This small comparison supports no claim beyond the displayed runs.

## Self-Review

- [x] Baseline and metric are named.
- [x] Numeric results point to the supplied experiment ledger.
