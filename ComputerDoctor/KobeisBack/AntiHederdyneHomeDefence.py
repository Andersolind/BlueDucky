mport numpy as np

class MeshFMTriangulator:
    def __init__(self, target_fm_frequency_hz=98.1e6, node1_rf_hz=915e6):
        """
        Calculates required distinct carrier offsets for an intersecting mesh
        to generate an 'instant' heterodyned FM station at a specific spatial point.
        """
        self.target_fm_freq = target_fm_frequency_hz
        self.node1_carrier = node1_rf_hz

        # Node 2 must transmit the sum frequency to force the targeted difference mix
        self.node2_carrier = self.node1_carrier + self.target_fm_freq
        self.speed_of_light = 3e8

        print(f"[*] Mesh Tuned: Node 1 Carrier = {self.node1_carrier/1e6:.1f} MHz")
        print(f"[*] Mesh Tuned: Node 2 Carrier = {self.node2_carrier/1e6:.1f} MHz")
        print(f"[+] Resulting Intersection Target Station: {self.target_fm_freq/1e6:.1f} MHz FM")

    def calculate_mesh_phase_alignment(self, target_ecef, node1_ecef, node2_ecef):
        """
        Computes the relative phase adjustments required for the mesh node 
        transmitters to constructively lock the heterodyned envelope on the target.
        """
        # Distances from nodes to target coordinate vector
        d1 = math.sqrt(sum((t - n)**2 for t, n in zip(target_ecef, node1_ecef)))
        d2 = math.sqrt(sum((t - n)**2 for t, n in zip(target_ecef, node2_ecef)))

        # Compute exact phase wrap-around metrics at the target intersection point
        lambda1 = self.speed_of_light / self.node1_carrier
        lambda2 = self.speed_of_light / self.node2_carrier

        phase1_rad = (2 * math.pi * (d1 % lambda1)) / lambda1
        phase2_rad = (2 * math.pi * (d2 % lambda2)) / lambda2

        # Returns the phase offset needed at Node 2 to match Node 1 at the target skin layer
        required_node2_phase_shift = (phase1_rad - phase2_rad) % (2 * math.pi)

        return {
            "node1_freq_hz": self.node1_carrier,
            "node2_freq_hz": self.node2_carrier,
            "node2_phase_correction_deg": math.degrees(required_node2_phase_shift)
        }