"""V4: bounded, causal factor-expression DSL; never evaluates arbitrary Python.

Each expression is parsed into an enumerated grammar and computed on aligned
date-by-security DataFrames. No imports, attributes, indexing, eval, or future
observations are supported.
"""
from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass

import numpy as np
import pandas as pd

_FIELDS = frozenset({'open', 'high', 'low', 'close', 'volume', 'daily_return'})
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.Mult: operator.mul, ast.Div: operator.truediv}
_FUNCTIONS = frozenset({'lag', 'ret', 'mean', 'std', 'sum', 'abs', 'rank', 'zscore'})
_MAX_CHARS = 512
_MAX_NODES = 70
_MAX_DEPTH = 12
_MAX_LOOKBACK = 252


@dataclass(frozen=True)
class CompiledExpression:
    formula: str
    lookback: int
    _tree: ast.Expression
    cross_sectional: bool = False

    def compute(self, context) -> pd.DataFrame:
        """Compute on aligned price panels; leave the inputs unchanged."""
        frames = {key: context.panels[key] for key in _FIELDS if key != 'daily_return'}
        frames['daily_return'] = context.returns

        def run(node):
            if isinstance(node, ast.Name):
                return frames[node.id]
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.UnaryOp):
                val = run(node.operand)
                return -val if isinstance(node.op, ast.USub) else val
            if isinstance(node, ast.BinOp):
                left, right = run(node.left), run(node.right)
                if isinstance(node.op, ast.Div):
                    if isinstance(right, (int, float)) and right == 0:
                        return context.close * np.nan
                    if isinstance(right, pd.DataFrame):
                        right = right.replace(0, np.nan)
                return _BINARY[type(node.op)](left, right)
            if isinstance(node, ast.Call):
                name = node.func.id
                first = run(node.args[0])
                if name == 'abs':
                    return abs(first)
                if name == 'rank':
                    return first.rank(axis=1, pct=True, method='average')
                if name == 'zscore':
                    mu = first.mean(axis=1)
                    sigma = first.std(axis=1, ddof=1).replace(0, np.nan)
                    return first.sub(mu, axis=0).div(sigma, axis=0)
                window = node.args[1].value
                if name == 'lag':
                    return first.shift(window)
                if name == 'ret':
                    return first.div(first.shift(window).replace(0, np.nan)) - 1
                roll = first.rolling(window, min_periods=window)
                if name == 'mean':
                    return roll.mean()
                if name == 'std':
                    return roll.std(ddof=1)
                if name == 'sum':
                    return roll.sum()
            raise AssertionError('Validated expression contains an unsupported node')

        value = run(self._tree.body)
        if not isinstance(value, pd.DataFrame):
            raise ValueError('A factor must depend on market data')
        if not value.index.equals(context.close.index) or not value.columns.equals(context.close.columns):
            raise ValueError('Expression changed calendar or security alignment')
        return value.replace([np.inf, -np.inf], np.nan).astype(float)


def compile_expression(formula: str) -> CompiledExpression:
    """Validate DSL and infer required historical lookback in sessions.

    Operators: + - * /; functions: lag, ret, mean, std, sum, abs,
    rank and zscore. All window sizes are literal positive integers <=252.
    """
    if not isinstance(formula, str) or not 1 <= len(formula.strip()) <= _MAX_CHARS:
        raise ValueError('Factor formula must be 1–512 characters')
    try:
        tree = ast.parse(formula, mode='eval')
    except SyntaxError as exc:
        raise ValueError('Invalid factor formula syntax') from exc
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ValueError('Factor formula exceeds operation limit')

    def review(node, depth=0):
        if depth > _MAX_DEPTH:
            raise ValueError('Factor formula exceeds maximum nesting depth')
        if isinstance(node, ast.Name):
            if node.id not in _FIELDS:
                raise ValueError(f'Unsupported factor field: {node.id}')
            return 1 if node.id == 'daily_return' else 0, True
        if isinstance(node, ast.Constant):
            if type(node.value) not in (int, float) or not math.isfinite(node.value) or abs(node.value) > 1e6:
                raise ValueError('Only bounded finite numeric literals are allowed')
            return 0, False
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return review(node.operand, depth + 1)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            a, first = review(node.left, depth + 1)
            b, second = review(node.right, depth + 1)
            return max(a, b), first or second
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS and not node.keywords:
            name = node.func.id
            if name in ('abs', 'rank', 'zscore'):
                if len(node.args) != 1:
                    raise ValueError(f'{name} expects one argument')
                lookback, depends = review(node.args[0], depth + 1)
            else:
                if len(node.args) != 2:
                    raise ValueError(f'{name} expects a panel and lookback')
                arg = node.args[1]
                if not isinstance(arg, ast.Constant) or type(arg.value) is not int:
                    raise ValueError('Lookback must be a literal integer')
                window = arg.value
                if not 1 <= window <= _MAX_LOOKBACK or (name == 'std' and window < 2):
                    raise ValueError('Lookback must be 1–252 (std requires >=2)')
                lookback, depends = review(node.args[0], depth + 1)
                if not depends:
                    raise ValueError(f'{name} requires market-data input')
                lookback += window if name in ('lag', 'ret') else window - 1
            if name in ('rank', 'zscore') and not depends:
                raise ValueError(f'{name} requires market-data input')
            if lookback > _MAX_LOOKBACK:
                raise ValueError('Nested rolling windows exceed 252 sessions')
            return lookback, depends
        raise ValueError(f'Disallowed factor syntax: {type(node).__name__}')

    lookback, depends = review(tree.body)
    if not depends:
        raise ValueError('A factor must depend on market data')
    cross_sectional = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id in ('rank', 'zscore') for node in ast.walk(tree))
    return CompiledExpression(formula.strip(), lookback, tree, cross_sectional)
