# Model-Agnostic Meta-Learning for Fast Adaptation of Deep Networks

<!-- Track-2 external test fixture. Provenance: title+abstract via arXiv API for
arXiv:1703.03400 (ICML 2017, 2017); Related Work prose and reference arXiv ids
extracted from ar5iv full text. Assembled, not authored. -->

## Abstract

We propose an algorithm for meta-learning that is model-agnostic, in the sense that it is compatible with any model trained with gradient descent and applicable to a variety of different learning problems, including classification, regression, and reinforcement learning. The goal of meta-learning is to train a model on a variety of learning tasks, such that it can solve new learning tasks using only a small number of training samples. In our approach, the parameters of the model are explicitly trained such that a small number of gradient steps with a small amount of training data from a new task will produce good generalization performance on that task. In effect, our method trains the model to be easy to fine-tune. We demonstrate that this approach leads to state-of-the-art performance on two few-shot image classification benchmarks, produces good results on few-shot regression, and accelerates fine-tuning for policy gradient reinforcement learning with neural network policies.

## Related Work

This work situates its contribution against the prior art listed in References.

## References

- [arXiv:1508.03854](https://arxiv.org/abs/1508.03854)
- [arXiv:1603.04467](https://arxiv.org/abs/1603.04467)
- [arXiv:1611.02779](https://arxiv.org/abs/1611.02779)
- [arXiv:1611.05763](https://arxiv.org/abs/1611.05763)
- [arXiv:1612.00796](https://arxiv.org/abs/1612.00796)
- [arXiv:1703.05175](https://arxiv.org/abs/1703.05175)
