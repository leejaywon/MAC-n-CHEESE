# Denoising Diffusion Probabilistic Models

<!-- Track-2 external test fixture. Provenance: title+abstract via arXiv API for
arXiv:2006.11239 (NeurIPS 2020, 2020); Related Work prose and reference arXiv ids
extracted from ar5iv full text. Assembled, not authored. -->

## Abstract

We present high quality image synthesis results using diffusion probabilistic models, a class of latent variable models inspired by considerations from nonequilibrium thermodynamics. Our best results are obtained by training on a weighted variational bound designed according to a novel connection between diffusion probabilistic models and denoising score matching with Langevin dynamics, and our models naturally admit a progressive lossy decompression scheme that can be interpreted as a generalization of autoregressive decoding. On the unconditional CIFAR10 dataset, we obtain an Inception score of 9.46 and a state-of-the-art FID score of 3.17. On 256x256 LSUN, we obtain sample quality similar to ProgressiveGAN. Our implementation is available at https://github.com/hojonathanho/diffusion

## Related Work

This work situates its contribution against the prior art listed in References.

## References

- [arXiv:1312.6114](https://arxiv.org/abs/1312.6114)
- [arXiv:1410.8516](https://arxiv.org/abs/1410.8516)
- [arXiv:1506.03365](https://arxiv.org/abs/1506.03365)
- [arXiv:1605.07146](https://arxiv.org/abs/1605.07146)
- [arXiv:1605.08803](https://arxiv.org/abs/1605.08803)
- [arXiv:1609.03499](https://arxiv.org/abs/1609.03499)
- [arXiv:1903.12370](https://arxiv.org/abs/1903.12370)
- [arXiv:1904.10509](https://arxiv.org/abs/1904.10509)
- [arXiv:2002.06707](https://arxiv.org/abs/2002.06707)
- [arXiv:2002.09928](https://arxiv.org/abs/2002.09928)
- [arXiv:2003.01599](https://arxiv.org/abs/2003.01599)
- [arXiv:2003.06060](https://arxiv.org/abs/2003.06060)
