"""
AI-Voice Spatial & Trajectory Tracking Module
=============================================
Implements:
1. TrajectoryInterceptor: Time-of-Flight (ToF) tracking, target distance prediction,
   and injection window delay calculations for acoustic wave streams.
2. SpatialDensityGrid: 2D Polar-to-Cartesian multipath vector density mapping
   for physical boundary visualization and radar persistence.
"""

import time
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from ai_voice.config import SpatialConfig

class TrajectoryInterceptor:
    """
    Tracks dynamic boundaries and calculates exact microsecond/millisecond timing delays
    needed to synchronize or inject acoustic pulses relative to a moving target.
    """

    def __init__(self, target_distance_init: float = 5.0, velocity: float = -0.5, speed_of_sound: float = 343.0):
        self.speed_of_sound = speed_of_sound
        self.current_distance = target_distance_init
        self.velocity = velocity  # m/s (negative = approaching)
        self.last_update = time.time()

    def update_velocity(self, new_velocity: float):
        self.velocity = new_velocity

    def set_distance(self, distance: float):
        self.current_distance = distance
        self.last_update = time.time()

    def track_and_predict_trajectory(self) -> float:
        """
        Predicts expected Time-of-Flight (seconds) based on target kinematics.
        """
        now = time.time()
        dt = max(0.0, now - self.last_update)
        self.last_update = now

        self.current_distance += self.velocity * dt
        # Clamp distance to realistic physical range
        self.current_distance = max(0.1, min(self.current_distance, 100.0))
        real_tof = self.current_distance / self.speed_of_sound
        return real_tof

    def calculate_injection_window(self, real_tof: float, spoof_distance: float = 3.0) -> Dict[str, Any]:
        """
        Computes timing delay and tactical status for synthetic pulse injection.
        """
        spoof_tof = spoof_distance / self.speed_of_sound
        spoof_delay_ms = spoof_tof * 1000.0
        real_delay_ms = real_tof * 1000.0
        
        if spoof_tof < real_tof:
            state = "INJECTION_VECTOR_VALID"
            lead_time_ms = (real_tof - spoof_tof) * 1000.0
        else:
            state = "TAIL_GATE_OVERRIDE_MODE"
            lead_time_ms = (spoof_tof - real_tof) * 1000.0

        return {
            "real_distance_m": round(real_tof * self.speed_of_sound, 3),
            "real_tof_ms": round(real_delay_ms, 3),
            "spoof_distance_m": round(spoof_distance, 3),
            "spoof_tof_ms": round(spoof_delay_ms, 3),
            "injection_delay_ms": round(spoof_delay_ms, 3),
            "lead_time_ms": round(lead_time_ms, 3),
            "state": state
        }


class SpatialDensityGrid:
    """
    Transforms resolved multi-path reflection vectors (distance, amplitude)
    into a 2D Cartesian spatial density matrix with radar persistence decay.
    """

    def __init__(self, config: Optional[SpatialConfig] = None):
        self.config = config or SpatialConfig()
        self.max_radius = self.config.max_room_radius_m
        self.resolution = self.config.grid_resolution_m
        self.grid_size = int((self.max_radius * 2) / self.resolution)
        self.spatial_grid = np.zeros((self.grid_size, self.grid_size), dtype=np.float32)
        self.decay_factor = 0.7
        self.new_weight = 0.3

    def update_vectors(self, vectors: List[Tuple[float, float]]) -> np.ndarray:
        """
        vectors: List of (distance_in_meters, amplitude)
        """
        new_intensities = np.zeros_like(self.spatial_grid)

        for distance, amplitude in vectors:
            if distance <= 0 or distance > self.max_radius:
                continue
            # Project circular wavefront into Cartesian grid
            angles = np.linspace(0, 2 * np.pi, num=180, endpoint=False)
            xs = distance * np.cos(angles)
            ys = distance * np.sin(angles)

            grid_xs = ((xs + self.max_radius) / self.resolution).astype(int)
            grid_ys = ((ys + self.max_radius) / self.resolution).astype(int)

            valid_mask = (grid_xs >= 0) & (grid_xs < self.grid_size) & (grid_ys >= 0) & (grid_ys < self.grid_size)
            np.add.at(new_intensities, (grid_ys[valid_mask], grid_xs[valid_mask]), float(amplitude))

        # Persistence decay (phosphor radar effect)
        self.spatial_grid = (self.spatial_grid * self.decay_factor) + (new_intensities * self.new_weight)
        return self.spatial_grid

    def get_grid(self) -> np.ndarray:
        return self.spatial_grid

    def get_normalized_grid(self) -> List[List[float]]:
        max_val = np.max(self.spatial_grid)
        if max_val > 0:
            norm = self.spatial_grid / max_val
        else:
            norm = self.spatial_grid
        return norm.tolist()

    def reset(self):
        self.spatial_grid.fill(0)
