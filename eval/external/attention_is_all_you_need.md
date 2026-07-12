# Attention Is All You Need

<!-- Track-2 external test fixture. Provenance: title+abstract via arXiv API for
arXiv:1706.03762 (NeurIPS 2017, 2017); Related Work prose and reference arXiv ids
extracted from ar5iv full text. Assembled, not authored. -->

## Abstract

The dominant sequence transduction models are based on complex recurrent or convolutional neural networks in an encoder-decoder configuration. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. Experiments on two machine translation tasks show these models to be superior in quality while being more parallelizable and requiring significantly less time to train. Our model achieves 28.4 BLEU on the WMT 2014 English-to-German translation task, improving over the existing best results, including ensembles by over 2 BLEU. On the WMT 2014 English-to-French translation task, our model establishes a new single-model state-of-the-art BLEU score of 41.8 after training for 3.5 days on eight GPUs, a small fraction of the training costs of the best models from the literature. We show that the Transformer generalizes well to other tasks by applying it successfully to English constituency parsing both with large and limited training data.

## Related Work

This work situates its contribution against the prior art listed in References.

## References

- [arXiv:1308.0850](https://arxiv.org/abs/1308.0850)
- [arXiv:1508.04025](https://arxiv.org/abs/1508.04025)
- [arXiv:1508.07909](https://arxiv.org/abs/1508.07909)
- [arXiv:1511.06114](https://arxiv.org/abs/1511.06114)
- [arXiv:1601.06733](https://arxiv.org/abs/1601.06733)
- [arXiv:1602.02410](https://arxiv.org/abs/1602.02410)
- [arXiv:1607.06450](https://arxiv.org/abs/1607.06450)
- [arXiv:1608.05859](https://arxiv.org/abs/1608.05859)
- [arXiv:1609.08144](https://arxiv.org/abs/1609.08144)
- [arXiv:1610.02357](https://arxiv.org/abs/1610.02357)
- [arXiv:1610.10099](https://arxiv.org/abs/1610.10099)
- [arXiv:1701.06538](https://arxiv.org/abs/1701.06538)
