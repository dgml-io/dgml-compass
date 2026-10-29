"""Shared fixtures."""

from __future__ import annotations

import pytest

from model_compass.corpus.shapes import load_shape_map

from .helpers import MINI


@pytest.fixture
def mini_shapes():
    return load_shape_map(MINI / "shapes.yaml")
