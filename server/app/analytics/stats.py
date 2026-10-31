"""Deterministic statistics used by the agents (no LLM involvement)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def wilson(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def two_prop_z(k1: float, n1: float, k2: float, n2: float) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (z, two-sided p). z>0 means group 1 has the higher rate."""
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-12))
    z = (k1 / n1 - k2 / n2) / se
    return z, float(2 * sps.norm.sf(abs(z)))


def poisson_anomaly(observed: float, expected: float) -> tuple[float, float]:
    """(z-score, upper-tail p-value) of an observed count against an expected Poisson mean."""
    expected = max(expected, 0.25)
    z = (observed - expected) / math.sqrt(expected)
    p = float(sps.poisson.sf(observed - 1, expected))
    return z, p


def rate(k: float, n: float) -> float:
    return float(k) / float(n) if n else 0.0


def binom_changepoint(k: np.ndarray, n: np.ndarray, min_seg: int = 3) -> dict | None:
    """Single change-point of a binomial rate via maximum likelihood-ratio split."""
    k, n = np.asarray(k, float), np.asarray(n, float)
    T = len(k)
    if T < 2 * min_seg or n.sum() == 0:
        return None

    def ll(kk, nn):
        if nn <= 0:
            return 0.0
        p = min(max(kk / nn, 1e-6), 1 - 1e-6)
        return kk * math.log(p) + (nn - kk) * math.log(1 - p)

    total = ll(k.sum(), n.sum())
    best = None
    for s in range(min_seg, T - min_seg + 1):
        llr = ll(k[:s].sum(), n[:s].sum()) + ll(k[s:].sum(), n[s:].sum()) - total
        if best is None or llr > best["llr"]:
            best = {"idx": s, "llr": llr, "rate_before": rate(k[:s].sum(), n[:s].sum()), "rate_after": rate(k[s:].sum(), n[s:].sum())}
    if best:
        best["p_value"] = float(sps.chi2.sf(2 * best["llr"], 1))
    return best


def mh_risk_difference(df: pd.DataFrame, exposed: pd.Series, strata: list[str]) -> dict | None:
    """Mantel-Haenszel stratified risk difference (exposed - unexposed) with a normal-approximation SE.

    Strata with only exposed or only unexposed units cannot inform the contrast and are dropped.
    Returns None when no stratum contains both groups (the exposure is fully confounded with the strata).
    """
    d = df.assign(_e=exposed.to_numpy())
    num = den = var = 0.0
    used = 0
    n_exp = 0
    for _, g in d.groupby(strata, dropna=False) if strata else [(None, d)]:
        e, u = g[g["_e"]], g[~g["_e"]]
        n1, n0 = e["n"].sum(), u["n"].sum()
        if n1 < 5 or n0 < 5:
            continue
        p1, p0 = e["k"].sum() / n1, u["k"].sum() / n0
        w = n1 * n0 / (n1 + n0)
        num += w * (p1 - p0)
        den += w
        var += (w ** 2) * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
        used += 1
        n_exp += n1
    if used == 0 or den == 0:
        return None
    rd = num / den
    se = math.sqrt(var) / den
    return {"rd": rd, "se": se, "z": rd / se if se > 0 else 0.0, "strata": used, "n_exposed": int(n_exp)}


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    adj = np.empty(n)
    prev = 1.0
    for rank, idx in reversed(list(enumerate(order, start=1))):
        prev = min(prev, pvals[idx] * n / rank)
        adj[idx] = prev
    return adj.tolist()


def fisher_greater(a: int, n_group: int, A: int, N: int) -> float:
    """P(affected count >= a) for a group of size n_group, given A affected overall among N customers."""
    table = [[a, n_group - a], [A - a, N - n_group - (A - a)]]
    if min(min(r) for r in table) < 0:
        return 1.0
    return float(sps.fisher_exact(table, alternative="greater")[1])


def spearman(x, y) -> float:
    if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    r = sps.spearmanr(x, y)[0]
    return 0.0 if np.isnan(r) else float(r)
