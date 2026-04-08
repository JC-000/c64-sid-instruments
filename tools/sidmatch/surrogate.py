"""Lightweight MLP surrogate for fitness pre-screening.

Pure-numpy two-layer MLP that predicts fitness from normalized parameter
vectors.  Used to pre-screen CMA-ES candidates so that only the most
promising ~50 % are evaluated with the expensive SID emulation pipeline.
"""

from __future__ import annotations

import numpy as np


class FitnessSurrogate:
    """Two-layer MLP that predicts fitness from normalized parameter vectors.

    Architecture: input → 64 → 64 → 1  (ReLU hidden, linear output).
    """

    def __init__(self, input_dim: int, hidden: int = 64):
        self.input_dim = input_dim
        self.hidden = hidden

        # Xavier initialization
        self.W1 = np.random.randn(input_dim, hidden).astype(np.float64) * np.sqrt(2.0 / input_dim)
        self.b1 = np.zeros(hidden, dtype=np.float64)
        self.W2 = np.random.randn(hidden, hidden).astype(np.float64) * np.sqrt(2.0 / hidden)
        self.b2 = np.zeros(hidden, dtype=np.float64)
        self.W3 = np.random.randn(hidden, 1).astype(np.float64) * np.sqrt(2.0 / hidden)
        self.b3 = np.zeros(1, dtype=np.float64)

        # Input/output normalization stats (set during fit)
        self._x_mean: np.ndarray | None = None
        self._x_std: np.ndarray | None = None
        self._y_mean: float = 0.0
        self._y_std: float = 1.0
        self._trained = False

    def _forward(self, X: np.ndarray) -> np.ndarray:
        """Forward pass. X shape: (n, input_dim). Returns (n, 1)."""
        h1 = X @ self.W1 + self.b1
        h1 = np.maximum(h1, 0.0)  # ReLU
        h2 = h1 @ self.W2 + self.b2
        h2 = np.maximum(h2, 0.0)  # ReLU
        out = h2 @ self.W3 + self.b3
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict fitness for multiple parameter vectors.

        Parameters
        ----------
        X : ndarray, shape (n, input_dim)
            Normalized parameter vectors (in [0, 1] CMA-ES space).

        Returns
        -------
        ndarray, shape (n,)
            Predicted fitness values.
        """
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        # Normalize inputs
        if self._x_mean is not None:
            X = (X - self._x_mean) / self._x_std
        raw = self._forward(X)  # (n, 1)
        # Denormalize output
        return (raw.ravel() * self._y_std) + self._y_mean

    def fit(self, X: np.ndarray, y: np.ndarray, epochs: int = 200,
            lr: float = 0.01, batch_size: int = 64) -> None:
        """Train on accumulated (params, fitness) pairs using mini-batch SGD.

        Parameters
        ----------
        X : ndarray, shape (n, input_dim)
        y : ndarray, shape (n,)
        epochs : int
        lr : float
        batch_size : int
        """
        X = np.asarray(X, dtype=np.float64).copy()
        y = np.asarray(y, dtype=np.float64).ravel().copy()
        n = X.shape[0]
        if n < 10:
            return  # not enough data

        # Compute and store normalization stats
        self._x_mean = X.mean(axis=0)
        self._x_std = X.std(axis=0)
        self._x_std[self._x_std < 1e-8] = 1.0
        self._y_mean = float(y.mean())
        self._y_std = float(y.std())
        if self._y_std < 1e-8:
            self._y_std = 1.0

        # Normalize
        X = (X - self._x_mean) / self._x_std
        y_norm = (y - self._y_mean) / self._y_std
        y_norm = y_norm.reshape(-1, 1)

        # Re-initialize weights for fresh training
        d = self.input_dim
        h = self.hidden
        self.W1 = np.random.randn(d, h).astype(np.float64) * np.sqrt(2.0 / d)
        self.b1 = np.zeros(h, dtype=np.float64)
        self.W2 = np.random.randn(h, h).astype(np.float64) * np.sqrt(2.0 / h)
        self.b2 = np.zeros(h, dtype=np.float64)
        self.W3 = np.random.randn(h, 1).astype(np.float64) * np.sqrt(2.0 / h)
        self.b3 = np.zeros(1, dtype=np.float64)

        for _epoch in range(epochs):
            # Shuffle
            perm = np.random.permutation(n)
            X = X[perm]
            y_norm = y_norm[perm]

            for start in range(0, n, batch_size):
                end = min(start + batch_size, n)
                Xb = X[start:end]
                yb = y_norm[start:end]
                bs = Xb.shape[0]

                # Forward pass
                z1 = Xb @ self.W1 + self.b1          # (bs, h)
                h1 = np.maximum(z1, 0.0)              # ReLU
                z2 = h1 @ self.W2 + self.b2           # (bs, h)
                h2 = np.maximum(z2, 0.0)              # ReLU
                out = h2 @ self.W3 + self.b3          # (bs, 1)

                # MSE loss gradient: d_loss/d_out = 2/bs * (out - yb)
                d_out = (2.0 / bs) * (out - yb)       # (bs, 1)

                # Backprop through output layer
                dW3 = h2.T @ d_out                     # (h, 1)
                db3 = d_out.sum(axis=0)                # (1,)

                # Backprop through second hidden layer
                d_h2 = d_out @ self.W3.T               # (bs, h)
                d_h2 = d_h2 * (z2 > 0).astype(np.float64)  # ReLU grad
                dW2 = h1.T @ d_h2                      # (h, h)
                db2 = d_h2.sum(axis=0)                 # (h,)

                # Backprop through first hidden layer
                d_h1 = d_h2 @ self.W2.T                # (bs, h)
                d_h1 = d_h1 * (z1 > 0).astype(np.float64)  # ReLU grad
                dW1 = Xb.T @ d_h1                      # (d, h)
                db1 = d_h1.sum(axis=0)                 # (h,)

                # SGD update
                self.W3 -= lr * dW3
                self.b3 -= lr * db3
                self.W2 -= lr * dW2
                self.b2 -= lr * db2
                self.W1 -= lr * dW1
                self.b1 -= lr * db1

        self._trained = True

    @property
    def is_ready(self) -> bool:
        """True if the model has been trained."""
        return self._trained
