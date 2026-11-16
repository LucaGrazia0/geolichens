"""Automatic base grid resolution shared by manual and automatic search areas."""

import math


def grid_step_for_radius(radius_m):
    radius = float(radius_m)
    if not math.isfinite(radius) or radius < 0:
        raise ValueError("Buffer radius must be a finite, non-negative distance")
    if radius <= 250:
        return 10.0
    if radius <= 1000:
        return 30.0
    if radius <= 3000:
        return 50.0
    return 100.0
