from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from typing import NoReturn
from unittest import mock
import warnings

import optuna
import pytest

from optuna_integration import WeightsAndBiasesCallback


def _objective_func(trial: optuna.trial.Trial) -> float:
    x = trial.suggest_float("x", low=-10, high=10)
    y = trial.suggest_float("y", low=1, high=10, log=True)
    return (x - 2) ** 2 + (y - 25) ** 2


def _multiobjective_func(trial: optuna.trial.Trial) -> tuple[float, float]:
    x = trial.suggest_float("x", low=-10, high=10)
    y = trial.suggest_float("y", low=1, high=10, log=True)
    first_objective = (x - 2) ** 2 + (y - 25) ** 2
    second_objective = (x - 2) ** 3 + (y - 25) ** 3

    return first_objective, second_objective


@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_run_initialized(wandb: mock.MagicMock) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    n_trials = 10
    wandb_kwargs = {
        "project": "optuna",
        "group": "summary",
        "job_type": "logging",
        "mode": "offline",
        "tags": ["test-tag"],
    }

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        WeightsAndBiasesCallback(metric_name="mse", wandb_kwargs=wandb_kwargs, as_multirun=False)
    wandb.init.assert_called_once_with(
        project="optuna", group="summary", job_type="logging", mode="offline", tags=["test-tag"]
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(
            metric_name="mse", wandb_kwargs=wandb_kwargs, as_multirun=True
        )
    wandb.run = None

    study = optuna.create_study(direction="minimize")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        _wrapped_func = wandbc.track_in_wandb()(lambda t: 1.0)
    wandb.init.reset_mock()
    trial = study.ask()
    _wrapped_func(trial)

    wandb.init.assert_called_once_with(
        project="optuna", group="summary", job_type="logging", mode="offline", tags=["test-tag"]
    )

    wandb.init.reset_mock()
    study.optimize(_objective_func, n_trials=n_trials, callbacks=[wandbc])

    wandb.init.assert_called_with(
        project="optuna", group="summary", job_type="logging", mode="offline", tags=["test-tag"]
    )

    assert wandb.init.call_count == n_trials

    wandb.init().finish.assert_called()
    assert wandb.init().finish.call_count == n_trials


@mock.patch("optuna_integration.wandb.wandb.wandb")
@pytest.mark.parametrize("as_multirun", [True, False])
def test_attributes_set_on_epoch(wandb: mock.MagicMock, as_multirun: bool) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    expected_config: dict[str, Any] = {"direction": ["MINIMIZE"]}
    trial_params = {"x": 1.1, "y": 2.2}
    expected_config_with_params = {**expected_config, **trial_params}

    study = optuna.create_study(direction="minimize")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(as_multirun=as_multirun)

    if as_multirun:
        wandb.run = None

    study.enqueue_trial(trial_params)
    study.optimize(_objective_func, n_trials=1, callbacks=[wandbc])

    if as_multirun:
        wandb.init().config.update.assert_called_once_with(expected_config_with_params)
    else:
        wandb.run.config.update.assert_called_once_with(expected_config)


@mock.patch("optuna_integration.wandb.wandb.wandb")
@pytest.mark.parametrize("as_multirun", [True, False])
def test_multiobjective_attributes_set_on_epoch(wandb: mock.MagicMock, as_multirun: bool) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    expected_config: dict[str, Any] = {"direction": ["MINIMIZE", "MAXIMIZE"]}
    trial_params = {"x": 1.1, "y": 2.2}
    expected_config_with_params = {**expected_config, **trial_params}

    study = optuna.create_study(directions=["minimize", "maximize"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(as_multirun=as_multirun)

    if as_multirun:
        wandb.run = None

    study.enqueue_trial(trial_params)
    study.optimize(_multiobjective_func, n_trials=1, callbacks=[wandbc])

    if as_multirun:
        wandb.init().config.update.assert_called_once_with(expected_config_with_params)
    else:
        wandb.run.config.update.assert_called_once_with(expected_config)


@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_log_api_call_count(wandb: mock.MagicMock) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    study = optuna.create_study()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback()

        @wandbc.track_in_wandb()
        def _decorated_objective(trial: optuna.trial.Trial) -> float:
            result = _objective_func(trial)
            wandb.run.log({"result": result})
            return result

    target_n_trials = 10
    study.optimize(_objective_func, n_trials=target_n_trials, callbacks=[wandbc])
    assert wandb.run.log.call_count == target_n_trials

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(as_multirun=True)
    wandb.run.reset_mock()

    study.optimize(_decorated_objective, n_trials=target_n_trials, callbacks=[wandbc])

    assert wandb.run.log.call_count == 2 * target_n_trials

    wandb.run = None
    study.optimize(_objective_func, n_trials=target_n_trials, callbacks=[wandbc])
    assert wandb.init().log.call_count == target_n_trials


@pytest.mark.parametrize(
    "metric,as_multirun,expected",
    [("value", False, ["x", "y", "value"]), ("foo", True, ["x", "y", "foo", "trial_number"])],
)
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_values_registered_on_epoch(
    wandb: mock.MagicMock, metric: str, as_multirun: bool, expected: list[str]
) -> None:
    def assert_call_args(log_func: mock.MagicMock, as_multirun: bool) -> None:
        call_args = log_func.call_args
        assert list(call_args[0][0].keys()) == expected
        assert call_args[1] == {"step": None if as_multirun else 0}

    wandb.sdk.wandb_run.Run = mock.MagicMock

    if as_multirun:
        wandb.run = None
        log_func = wandb.init().log
    else:
        log_func = wandb.run.log

    study = optuna.create_study()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(metric_name=metric, as_multirun=as_multirun)
    study.optimize(_objective_func, n_trials=1, callbacks=[wandbc])
    assert_call_args(log_func, as_multirun)


@pytest.mark.parametrize("metric,expected", [("foo", ["x", "y", "foo", "trial_number"])])
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_values_registered_on_epoch_with_logging(
    wandb: mock.MagicMock, metric: str, expected: list[str]
) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    study = optuna.create_study()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(metric_name=metric, as_multirun=True)

        @wandbc.track_in_wandb()
        def _decorated_objective(trial: optuna.trial.Trial) -> float:
            result = _objective_func(trial)
            wandb.run.log({"result": result})
            return result

    study.enqueue_trial({"x": 2, "y": 3})
    study.optimize(_decorated_objective, n_trials=1, callbacks=[wandbc])

    logged_in_decorator = wandb.run.log.mock_calls[0][1][0]
    logged_in_callback = wandb.run.log.mock_calls[1][1][0]
    assert len(wandb.run.log.mock_calls) == 2
    assert list(logged_in_decorator) == ["result"]
    assert list(logged_in_callback) == expected

    call_args = wandb.run.log.call_args
    assert call_args[1] == {"step": 0}


@pytest.mark.parametrize(
    "metrics,as_multirun,expected",
    [
        ("value", False, ["x", "y", "value_0", "value_1"]),
        ("value", True, ["x", "y", "value_0", "value_1", "trial_number"]),
        (["foo", "bar"], False, ["x", "y", "foo", "bar"]),
        (("foo", "bar"), True, ["x", "y", "foo", "bar", "trial_number"]),
    ],
)
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_multiobjective_values_registered_on_epoch(
    wandb: mock.MagicMock,
    metrics: str | Sequence[str],
    as_multirun: bool,
    expected: list[str],
) -> None:
    def assert_call_args(log_func: mock.MagicMock, as_multirun: bool) -> None:
        call_args = log_func.call_args
        assert list(call_args[0][0].keys()) == expected
        assert call_args[1] == {"step": None if as_multirun else 0}

    wandb.sdk.wandb_run.Run = mock.MagicMock

    if as_multirun:
        wandb.run = None
        log_func = wandb.init().log
    else:
        log_func = wandb.run.log

    study = optuna.create_study(directions=["minimize", "maximize"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(metric_name=metrics, as_multirun=as_multirun)

    study.optimize(_multiobjective_func, n_trials=1, callbacks=[wandbc])
    assert_call_args(log_func, as_multirun)


@pytest.mark.parametrize(
    "metrics,expected",
    [
        ("value", ["x", "y", "value_0", "value_1", "trial_number"]),
        (("foo", "bar"), ["x", "y", "foo", "bar", "trial_number"]),
    ],
)
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_multiobjective_values_registered_on_epoch_with_logging(
    wandb: mock.MagicMock, metrics: str | Sequence[str], expected: list[str]
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(as_multirun=True, metric_name=metrics)

        @wandbc.track_in_wandb()
        def _decorated_objective(trial: optuna.trial.Trial) -> tuple[float, float]:
            result0, result1 = _multiobjective_func(trial)
            wandb.run.log({"result0": result0, "result1": result1})
            return result0, result1

    study = optuna.create_study(directions=["minimize", "maximize"])
    study.enqueue_trial({"x": 2, "y": 3})
    study.optimize(_decorated_objective, n_trials=1, callbacks=[wandbc])

    logged_in_decorator = wandb.run.log.mock_calls[0][1][0]
    logged_in_callback = wandb.run.log.mock_calls[1][1][0]

    assert len(wandb.run.log.mock_calls) == 2
    assert list(logged_in_decorator) == ["result0", "result1"]
    assert list(logged_in_callback) == expected

    call_args = wandb.run.log.call_args
    assert call_args[1] == {"step": 0}


@pytest.mark.parametrize("metrics", [["foo"], ["foo", "bar", "baz"]])
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_multiobjective_raises_on_name_mismatch(wandb: mock.MagicMock, metrics: list[str]) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    study = optuna.create_study(directions=["minimize", "maximize"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback(metric_name=metrics)

    with pytest.raises(ValueError):
        study.optimize(_multiobjective_func, n_trials=1, callbacks=[wandbc])


@pytest.mark.parametrize("exception", [optuna.exceptions.TrialPruned, ValueError])
@mock.patch("optuna_integration.wandb.wandb.wandb")
def test_none_values(wandb: mock.MagicMock, exception: type[Exception]) -> None:
    wandb.sdk.wandb_run.Run = mock.MagicMock

    study = optuna.create_study()

    def none_objective_func(trial: optuna.trial.Trial) -> NoReturn:
        trial.suggest_float("x", -10, 10)
        raise exception()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", optuna.exceptions.ExperimentalWarning)
        wandbc = WeightsAndBiasesCallback()

    study.optimize(none_objective_func, n_trials=1, callbacks=[wandbc], catch=(ValueError,))

    logged_keys = list(wandb.run.log.call_args[0][0].keys())

    assert "value" not in logged_keys
    assert "x" in logged_keys
