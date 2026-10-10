"""Diagnostic only: run with the wall clock on a weekday (Wednesday 12:00 UTC)."""
import time_machine

_TRAVELLER = time_machine.travel("2026-10-07 12:00:00+00:00", tick=True)


def pytest_configure(config):
    _TRAVELLER.start()


def pytest_unconfigure(config):
    _TRAVELLER.stop()
