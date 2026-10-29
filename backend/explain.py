"""
Explainable risk assessment.

The risk engine is a scikit-learn ``Pipeline`` of ``StandardScaler`` and
``LogisticRegression``. That is a *linear* model, so the contribution of
each input to the final score can be computed exactly rather than
approximated:

    log-odds(x) = intercept + sum(coef_i * z_i)
    z_i         = (x_i - mean_i) / scale_i

Each term ``coef_i * z_i`` is that feature's exact contribution to the
log-odds. The contributions sum to ``log-odds(x) - intercept``, which is
the distance the assessment moved away from the model's baseline.

Two explanation methods are supported, and only the ones the loaded
artifact can actually produce:

``linear_contribution``
    Exact per-feature decomposition of the log-odds. Available for any
    artifact whose final estimator exposes ``coef_`` / ``intercept_``
    (linear models).

``permutation_importance``
    Mean decrease in suspicious probability when one feature is
    shuffled across a sample of *real* historical feature vectors. It
    is model-agnostic, so it is the fallback when the artifact is not
    linear, and a useful cross-check when it is.

Both methods read the feature vector that was actually scored (stored
with the prediction), never a re-derived guess.

Nothing in this module changes the risk score: the model output is the
model output. The explanation is only ever an interpretation of it.
"""

import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------
# Method availability
# ---------------------------------------------------------------

EXPLANATION_LINEAR = "linear_contribution"
EXPLANATION_PERMUTATION = "permutation_importance"


def _final_estimator(model):
    """Return the estimator that actually produces the score."""

    steps = getattr(model, "named_steps", None)

    if steps:
        for name in reversed(list(steps.keys())):
            return steps[name]

    return model


def _preprocessing_steps(model):
    """Return the (name, transformer) pairs applied before the estimator."""

    steps = getattr(model, "named_steps", None)

    if not steps:
        return []

    final = _final_estimator(model)

    return [
        (name, transformer)
        for name, transformer in steps.items()
        if transformer is not final
    ]


def supported_methods(model):
    """
    Return the explanation methods the loaded artifact supports.

    A method is only listed when the artifact really can produce it, so
    the API never advertises an explanation it cannot compute.
    """

    estimator = _final_estimator(model)

    methods = []

    if hasattr(estimator, "coef_") and hasattr(estimator, "intercept_"):
        methods.append(EXPLANATION_LINEAR)

    if hasattr(estimator, "predict_proba"):
        methods.append(EXPLANATION_PERMUTATION)

    return methods


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _sigmoid(value):
    value = max(-500.0, min(500.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def _standardise(model, features, values):
    """
    Apply the pipeline's preprocessing to one feature vector.

    Returns (z_values, means, scales). When the pipeline has no
    scaler the raw values are returned unchanged.
    """

    means = {}
    scales = {}

    raw = {
        feature: float(values[feature])
        for feature in features
    }

    for name, transformer in _preprocessing_steps(model):
        if hasattr(transformer, "mean_") and hasattr(transformer, "scale_"):
            means = {
                feature: float(mean)
                for feature, mean in zip(features, transformer.mean_)
            }
            scales = {
                feature: float(scale) if float(scale) else 1.0
                for feature, scale in zip(features, transformer.scale_)
            }
            break

    if not means:
        return raw, {}, {}

    standardised = {
        feature: (
            raw[feature] - means.get(feature, 0.0)
        ) / scales.get(feature, 1.0)
        for feature in features
    }

    return standardised, means, scales


def _log_odds(model, features, values):
    """Compute the model's log-odds for one feature vector."""

    estimator = _final_estimator(model)

    frame = pd.DataFrame(
        [[float(values[feature]) for feature in features]],
        columns=features
    )

    for _, transformer in _preprocessing_steps(model):
        if hasattr(transformer, "transform"):
            frame = transformer.transform(frame)

    log_odds = float(estimator.decision_function(frame)[0])

    return log_odds


# ---------------------------------------------------------------
# Method 1: exact linear contribution
# ---------------------------------------------------------------

def linear_contribution(model, features, values):
    """
    Decompose one prediction into per-feature contributions.

    Each contribution is the exact change that feature made to the
    log-odds, so the contributions add up to
    ``log_odds - intercept``.
    """

    estimator = _final_estimator(model)

    coefficients = np.asarray(estimator.coef_).ravel()

    standardised, means, scales = _standardise(
        model,
        features,
        values
    )

    intercept = float(
        np.asarray(estimator.intercept_).ravel()[0]
    )

    contributions = []
    total = 0.0

    for index, feature in enumerate(features):
        coefficient = float(coefficients[index])
        z_value = float(standardised[feature])
        contribution = coefficient * z_value
        total += contribution

        contributions.append({
            "feature": feature,
            "value": float(values[feature]),
            "standardised_value": round(z_value, 6),
            "coefficient": round(coefficient, 6),
            "contribution": round(contribution, 6),
            "direction": (
                "increases_risk"
                if contribution > 0
                else ("decreases_risk" if contribution < 0 else "neutral")
            ),
            "population_mean": (
                round(means[feature], 6) if feature in means else None
            ),
            "population_std": (
                round(scales[feature], 6) if feature in scales else None
            ),
        })

    contributions.sort(
        key=lambda item: abs(item["contribution"]),
        reverse=True
    )

    return {
        "method": EXPLANATION_LINEAR,
        "base_value": round(intercept, 6),
        "base_probability": round(_sigmoid(intercept), 6),
        "log_odds": round(intercept + total, 6),
        "contributions": contributions,
        "total_contribution": round(total, 6),
    }


# ---------------------------------------------------------------
# Method 2: permutation importance over real inputs
# ---------------------------------------------------------------

def permutation_importance(model, features, samples, seed=42,
                           repeats=5):
    """
    Mean decrease in suspicious probability when a feature is shuffled.

    ``samples`` must be a list of real feature vectors (dicts). When it
    is empty the method reports that it is unavailable rather than
    inventing a number.
    """

    if not samples:
        return {
            "method": EXPLANATION_PERMUTATION,
            "available": False,
            "reason": (
                "No historical feature vectors are stored yet. "
                "The linear contribution is still available."
            ),
            "importances": [],
        }

    frame = pd.DataFrame(
        [
            [float(sample[feature]) for feature in features]
            for sample in samples
        ],
        columns=features
    )

    estimator = _final_estimator(model)

    prepared = frame
    for _, transformer in _preprocessing_steps(model):
        if hasattr(transformer, "transform"):
            prepared = transformer.transform(prepared)

    base = np.asarray(
        estimator.predict_proba(prepared)[:, 1]
    ).ravel()

    baseline = float(base.mean())

    generator = np.random.default_rng(seed)

    importances = []

    for index, feature in enumerate(features):
        drops = []

        for _ in range(repeats):
            shuffled = frame.copy()
            shuffled[feature] = generator.permutation(
                shuffled[feature].to_numpy()
            )

            shuffled_prepared = shuffled
            for _, transformer in _preprocessing_steps(model):
                if hasattr(transformer, "transform"):
                    shuffled_prepared = transformer.transform(
                        shuffled_prepared
                    )

            probability = np.asarray(
                estimator.predict_proba(shuffled_prepared)[:, 1]
            ).ravel()

            drops.append(baseline - float(probability.mean()))

        importances.append({
            "feature": feature,
            "importance": round(float(np.mean(drops)), 6),
            "std": round(float(np.std(drops)), 6),
        })

    importances.sort(
        key=lambda item: abs(item["importance"]),
        reverse=True
    )

    return {
        "method": EXPLANATION_PERMUTATION,
        "available": True,
        "sample_count": len(samples),
        "repeats": repeats,
        "baseline_probability": round(baseline, 6),
        "importances": importances,
    }


# ---------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------

def explain_prediction(model, features, values, background_samples=None):
    """
    Explain one scored request.

    ``values`` must be the feature vector that was actually scored.
    ``background_samples`` is a list of real historical feature vectors
    used by the permutation method.

    The result always carries a human-readable summary and the exact
    contributions when the artifact supports them.
    """

    available = supported_methods(model)

    result = {
        "methods_available": available,
        "features": list(features),
        "inputs": {feature: float(values[feature]) for feature in features},
    }

    if EXPLANATION_LINEAR in available:
        linear = linear_contribution(model, features, values)
        result["primary"] = linear
        result["summary"] = _summarise(linear)
    else:
        result["primary"] = None
        result["summary"] = (
            "This model cannot be decomposed into exact per-feature "
            "contributions. The permutation importances below show "
            "which inputs matter most overall."
        )

    if EXPLANATION_PERMUTATION in available:
        result["permutation_importance"] = permutation_importance(
            model,
            features,
            background_samples or []
        )

    return result


def _summarise(linear):
    """One sentence describing the two strongest contributions."""

    contributions = [
        item for item in linear["contributions"]
        if abs(item["contribution"]) > 1e-9
    ]

    if not contributions:
        return (
            "No individual input moved the score away from the "
            "model baseline."
        )

    top = contributions[0]

    direction = (
        "raised" if top["contribution"] > 0 else "lowered"
    )

    return (
        f"The strongest driver was '{top['feature']}', which "
        f"{direction} the risk score by "
        f"{abs(top['contribution']):.2f} log-odds points."
    )
