"""User-randomized inference; repeated impressions are never independent trials."""
from __future__ import annotations

from typing import Any

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import chi2_contingency, fisher_exact, norm


def binary_comparison(control_success: int, control_n: int,
                      treatment_success: int, treatment_n: int) -> dict:
    """Two-sided pooled Z/Pearson tests on one binary observation per user."""
    if min(control_n, treatment_n) < 1 or not (
        0 <= control_success <= control_n and 0 <= treatment_success <= treatment_n
    ):
        raise ValueError('invalid independent-user counts')
    pc, pt = control_success / control_n, treatment_success / treatment_n
    pooled = (control_success + treatment_success) / (control_n + treatment_n)
    variance = pooled * (1 - pooled) * (1 / control_n + 1 / treatment_n)
    z = (pt - pc) / math.sqrt(variance) if variance else 0.0
    table = [[control_success, control_n - control_success],
             [treatment_success, treatment_n - treatment_success]]
    if pooled in (0, 1):
        chi, chi_p, low = 0.0, 1.0, True
    else:
        chi, chi_p, _, expected = chi2_contingency(table, correction=False)
        low = bool((expected < 5).any())
    standard_error = math.sqrt(pc * (1 - pc) / control_n + pt * (1 - pt) / treatment_n)
    margin = float(norm.ppf(0.975)) * standard_error
    return dict(control=pc, treatment=pt, difference=pt - pc,
                relative_lift=(pt / pc - 1) if pc else None,
                z_statistic=z, z_p_value=float(2 * norm.sf(abs(z))),
                chi_square=float(chi), chi_square_p_value=float(chi_p),
                difference_ci95=[max(-1., pt - pc - margin), min(1., pt - pc + margin)],
                ci_method='unpooled user-risk Wald; degenerate at boundary counts',
                low_expected_counts=low, asymptotic_reliable=not low,
                fisher_p_value=float(fisher_exact(table).pvalue) if low else None,
                experimental_unit='one independent randomized user')


def clustered_rate(control: Sequence[Mapping[str, Any]], treatment: Sequence[Mapping[str, Any]],
                   numerator: str, denominator: str) -> dict:
    """Ratio-of-totals delta CI using independent user clusters, not impressions."""
    def estimate(rows: Any) -> tuple[float | None, float | None]:
        n = np.array([r[numerator] for r in rows], dtype=float)
        d = np.array([r[denominator] for r in rows], dtype=float)
        if (n < 0).any() or (d < n).any():
            raise ValueError('rate requires 0 <= numerator <= denominator')
        if len(rows) < 2 or d.sum() == 0:
            return None, None
        rate = float(n.sum() / d.sum())
        variance = float(len(rows) / (len(rows) - 1) * np.square(n - rate * d).sum() / d.sum() ** 2)
        return rate, variance
    pc, vc = estimate(control)
    pt, vt = estimate(treatment)
    if pc is None or pt is None:
        return dict(status='UNMEASURED', control=pc, treatment=pt, difference=None,
                    relative_lift=None, difference_ci95=None, z_p_value=None,
                    reason='at least two users/arm and nonzero denominators required')
    difference = pt - pc
    assert vc is not None and vt is not None
    se = math.sqrt(vc + vt)
    z = difference / se if se else None
    return dict(status='PASS' if se else 'DEGENERATE', control=pc, treatment=pt,
                difference=difference, relative_lift=pt / pc - 1 if pc else None,
                difference_ci95=[max(-1., difference - 1.959963984540054 * se),
                                 min(1., difference + 1.959963984540054 * se)],
                z_p_value=float(2 * norm.sf(abs(z))) if z is not None else None,
                method='independent-user cluster delta variance; descriptive simulated effect')
