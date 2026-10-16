"""Configurable bandit strategies; exposure and max reward state belongs to the store."""
from __future__ import annotations

from typing import Any, Callable

from typing import Protocol
import numpy as np


class BanditStrategy(Protocol):
    def select(self, items: list[str], stats: dict, arm_for: Callable[[str], str], rng: np.random.Generator, count: int) -> list[str]: ...


class EpsilonGreedy:
    def __init__(self, epsilon: float):
        if not 0 <= epsilon <= 1: raise ValueError('epsilon must be in [0,1]')
        self.epsilon=epsilon

    def select(self, items: Any, stats: dict, arm_for: Callable[[str], str], rng: Any, count: int) -> Any:
        pool=list(dict.fromkeys(items)); picked=[]
        for _ in range(min(count,len(pool))):
            if rng.random()<self.epsilon:
                product=pool[int(rng.integers(len(pool)))]
            else:
                product=max(pool,key=lambda p:stats.get(arm_for(p),{}).get('reward',0)/max(1,stats.get(arm_for(p),{}).get('exposures',0)))
            picked.append(product); pool.remove(product)
        return picked


class UCB:
    def __init__(self, coefficient: float):
        if coefficient <= 0: raise ValueError('UCB coefficient must be positive')
        self.coefficient=coefficient

    def select(self, items: Any, stats: dict, arm_for: Callable[[str], str], rng: Any, count: int) -> Any:
        total=max(2,sum(s['exposures'] for s in stats.values()))
        def score(product: Any) -> float:
            state=stats.get(arm_for(product),{}); n=state.get('exposures',0)
            return float('inf') if not n else state.get('reward',0)/n+self.coefficient*np.sqrt(np.log(total)/n)
        return sorted(dict.fromkeys(items),key=lambda p:-score(p))[:count]


def create_strategy(spec: dict) -> BanditStrategy:
    if spec['algo']=='epsilon_greedy': return EpsilonGreedy(float(spec['epsilon']))
    if spec['algo']=='ucb': return UCB(float(spec['ucb_coefficient']))
    raise ValueError(f'unsupported MAB strategy: {spec["algo"]}')
