#!/usr/bin/env python3
"""
Multi-Node Ultrasonic TOF Self-Calibration & 10m x 10m Spatial Trajectory Engine
================================================================================
Implements:
1. execute_hardware_self_calibration(tof_12, tof_13):
   Uses ultrasonic time-of-flight (TOF) acoustic chimes (c = 343.0 m/s) between
   NODE_1 (fixed master anchor [0, 10]), NODE_2 ([0, y2]), and NODE_3 ([x3, 0])
   to dynamically recalibrate room anchor geometry when a node is shifted.
2. compute_spatial_trajectory_overlay(x_coord, y_coord):
   Normalizes (x, y) into 0-100% schematic coordinates across the 10m x 10m room
   and classifies the target into the four architectural sector quadrants:
     - NORTHEAST_QUADRANT (Living Room Window Path)
     - NORTHWEST_QUADRANT (Hallway Entry Transition Line)
     - SOUTHEAST_QUADRANT (Staircase Ascent Access Corridor)
     - SOUTHWEST_QUADRANT (Dampened Bedroom Perimeter)
3. Multi-node TDOA/TOF trilateration residual & trajectory history buffer.
"""

import asyncio
import datetime
import math
import time
from collections import deque
from dataclasses import dataclass, asdict
from typing import Dict, List
import numpy as np

# Spatial Map Geometry Limits (in Metres)
ROOM_WIDTH_M = 10.0
ROOM_HEIGHT_M = 10.0
SOUND_SPEED_M_S = 343.0  # Speed of sound in room temperature air

# Active Calibration State Coordinates Cache
NODE_GEOMETRY = {
    "NODE_1": np.array([0.0, 10.0]),  # Primary Node Location Baseline
    "NODE_2": np.array([0.0, 0.0]),   # Secondary Node Location Baseline
    "NODE_3": np.array([10.0, 0.0]),  # Tertiary Node Location Baseline
}


def execute_hardware_self_calibration(tof_12: float, tof_13: float):
    """
    [SELF-CALIBRATION MATRIX]: Uses ultrasonic time-of-flight (TOF) chimes
    to automatically compute exact geometric distances if a node is shifted.
    """
    global NODE_GEOMETRY
    dist_12 = max(1.0, float(tof_12) * SOUND_SPEED_M_S)
    dist_13 = max(1.0, float(tof_13) * SOUND_SPEED_M_S)

    NODE_GEOMETRY["NODE_2"] = np.array([0.0, max(0.0, float(NODE_GEOMETRY["NODE_1"][1]) - dist_12)])
    NODE_GEOMETRY["NODE_3"] = np.array([max(0.0, dist_13), 0.0])
    return NODE_GEOMETRY


def compute_spatial_trajectory_overlay(x_coord: float, y_coord: float) -> Dict:
    """
    Generates structured 2D visual trajectory coordinate logging blocks
    to map real-time tracking points onto the 10m x 10m room schematic layout.
    """
    x_percent = min(100.0, max(0.0, (float(x_coord) / ROOM_WIDTH_M) * 100.0))
    y_percent = min(100.0, max(0.0, (float(y_coord) / ROOM_HEIGHT_M) * 100.0))

    if x_coord > 5.0 and y_coord > 5.0:
        sector_zone = "NORTHEAST_QUADRANT (Living Room Window Path)"
    elif x_coord <= 5.0 and y_coord > 5.0:
        sector_zone = "NORTHWEST_QUADRANT (Hallway Entry Transition Line)"
    elif x_coord > 5.0 and y_coord <= 5.0:
        sector_zone = "SOUTHEAST_QUADRANT (Staircase Ascent Access Corridor)"
    else:
        sector_zone = "SOUTHWEST_QUADRANT (Dampened Bedroom Perimeter)"

    return {
        "x_coord_m": round(float(x_coord), 2),
        "y_coord_m": round(float(y_coord), 2),
        "x_map_pct": f"{x_percent:.1f}%",
        "y_map_pct": f"{y_percent:.1f}%",
        "x_pct_num": round(x_percent, 1),
        "y_pct_num": round(y_percent, 1),
        "zone_descriptor": sector_zone,
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
    }


@dataclass
class SpatialCalibrationConfig:
    tof_12_sec: float = 0.02915   # ~10.0 m default chime TOF (Node 1 -> Node 2)
    tof_13_sec: float = 0.02915   # ~10.0 m default chime TOF (Node 1 -> Node 3)
    target_x_m: float = 6.8
    target_y_m: float = 7.2
    auto_orbit_target: bool = True
    orbit_speed_rad_s: float = 0.35


class SpatialTofCalibrationEngine:
    """Stateful manager for 3-node ultrasonic TOF self-calibration & trajectory overlay."""

    def __init__(self):
        self.cfg = SpatialCalibrationConfig()
        self.trajectory_trail: deque = deque(maxlen=45)
        self.calibration_logs: deque = deque(maxlen=25)
        self.calibration_count = 0
        self.last_calibrated_ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._apply_calibration(self.cfg.tof_12_sec, self.cfg.tof_13_sec)

    def _apply_calibration(self, tof_12_sec: float, tof_13_sec: float) -> None:
        self.cfg.tof_12_sec = float(tof_12_sec)
        self.cfg.tof_13_sec = float(tof_13_sec)
        execute_hardware_self_calibration(self.cfg.tof_12_sec, self.cfg.tof_13_sec)
        self.calibration_count += 1
        self.last_calibrated_ts = datetime.datetime.now().strftime("%H:%M:%S")
        dist_12 = round(float(np.linalg.norm(NODE_GEOMETRY["NODE_1"] - NODE_GEOMETRY["NODE_2"])), 2)
        baseline_13 = round(float(NODE_GEOMETRY["NODE_3"][0]), 2)
        self.calibration_logs.appendleft({
            "timestamp": self.last_calibrated_ts,
            "NODE_1": [round(float(NODE_GEOMETRY["NODE_1"][0]), 2), round(float(NODE_GEOMETRY["NODE_1"][1]), 2)],
            "NODE_2": [round(float(NODE_GEOMETRY["NODE_2"][0]), 2), round(float(NODE_GEOMETRY["NODE_2"][1]), 2)],
            "NODE_3": [round(float(NODE_GEOMETRY["NODE_3"][0]), 2), round(float(NODE_GEOMETRY["NODE_3"][1]), 2)],
            "dist_12_m": dist_12,
            "dist_13_m": baseline_13,
            "tof_12_sec": round(self.cfg.tof_12_sec, 5),
            "tof_13_sec": round(self.cfg.tof_13_sec, 5),
        })

    def recalibrate(self, tof_12_sec: float, tof_13_sec: float) -> Dict:
        self._apply_calibration(tof_12_sec, tof_13_sec)
        return self.step_telemetry()

    def step_telemetry(self) -> Dict:
        t = time.time()
        if self.cfg.auto_orbit_target:
            w = float(self.cfg.orbit_speed_rad_s)
            cx = 5.0 + 3.2 * math.cos(t * w)
            cy = 5.0 + 3.1 * math.sin(t * w * 0.85)
            self.cfg.target_x_m = round(float(np.clip(cx, 0.4, 9.6)), 2)
            self.cfg.target_y_m = round(float(np.clip(cy, 0.4, 9.6)), 2)

        tx = float(self.cfg.target_x_m)
        ty = float(self.cfg.target_y_m)
        overlay = compute_spatial_trajectory_overlay(tx, ty)

        # Prevent duplicate consecutive trail points if static
        if not self.trajectory_trail or (
            abs(self.trajectory_trail[0]["x_coord_m"] - tx) > 0.05
            or abs(self.trajectory_trail[0]["y_coord_m"] - ty) > 0.05
        ):
            self.trajectory_trail.appendleft(overlay)

        p_target = np.array([tx, ty])
        nodes_dict = {}
        node_ranges = {}
        node_tofs_ms = {}

        for name, vec in NODE_GEOMETRY.items():
            coords = [round(float(vec[0]), 2), round(float(vec[1]), 2)]
            nodes_dict[name] = coords
            dist = float(np.linalg.norm(p_target - vec))
            node_ranges[name] = round(dist, 2)
            node_tofs_ms[name] = round((dist / SOUND_SPEED_M_S) * 1000.0, 2)

        dist_12 = round(float(np.linalg.norm(NODE_GEOMETRY["NODE_1"] - NODE_GEOMETRY["NODE_2"])), 2)
        baseline_13 = round(float(NODE_GEOMETRY["NODE_3"][0]), 2)
        area_m2 = round(0.5 * dist_12 * baseline_13, 2)

        return {
            "room_limits_m": {
                "width": ROOM_WIDTH_M,
                "height": ROOM_HEIGHT_M,
                "sound_speed_m_s": SOUND_SPEED_M_S,
                "sound_speed_ms": SOUND_SPEED_M_S,
            },
            "node_geometry": nodes_dict,
            "calibrated_baselines_m": {
                "dist_12_m": dist_12,
                "dist_13_m": baseline_13,
                "area_m2": area_m2,
                "tof_12_ms": round(self.cfg.tof_12_sec * 1000.0, 2),
                "tof_13_ms": round(self.cfg.tof_13_sec * 1000.0, 2),
                "calibration_count": self.calibration_count,
                "last_calibrated_ts": self.last_calibrated_ts,
            },
            "target_ranges_m": node_ranges,
            "target_tofs_ms": node_tofs_ms,
            "current_overlay": overlay,
            "calibration_logs": list(self.calibration_logs),
            "trajectory_trail": list(self.trajectory_trail)[:25],
            "params": asdict(self.cfg),
        }


if __name__ == "__main__":
    eng = SpatialTofCalibrationEngine()
    snap = eng.recalibrate(0.025, 0.028)
    print("Nodes:", snap["node_geometry"], "| Overlay:", snap["current_overlay"])
