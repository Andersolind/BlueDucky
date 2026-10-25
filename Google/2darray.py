import time
import numpy as np
import scipy.signal as signal

class TrajectoryInterceptor:
    def __init__(self, target_distance_init=5.0, velocity=-0.5):
        self.speed_of_sound = 343.0  # m/s
        self.current_distance = target_distance_init
        self.velocity = velocity      # m/s (negative means moving closer)
        self.last_update = time.time()
        
    def track_and_predict_trajectory(self):
        """
        Calculates the real target's movement to predict exactly where 
        its next reflection wave will appear in the time domain.
        """
        now = time.time()
        dt = now - self.last_update
        self.last_update = now
        
        # Update physical track position model
        self.current_distance += self.velocity * dt
        
        # Calculate real expected Time-of-Flight (seconds)
        real_tof = self.current_distance / self.speed_of_sound
        return real_tof

    def calculate_injection_window(self, real_tof, spoof_distance=3.0):
        """
        Computes the precise timing delay needed to piggyback on the stream.
        To hijack the path, your fake pulse must arrive slightly BEFORE the real reflection.
        """
        # Calculate your desired fake position's Time-of-Flight
        spoof_tof = spoof_distance / self.speed_of_sound
        
        # Delta-time window check
        if spoof_tof < real_tof:
            # Your path is shorter/faster; you can cleanly inject ahead of the real wave
            injection_delay_ms = spoof_tof * 1000.0
            status = "INJECTION VECTOR VALID"
        else:
            # Your fake path is behind the real reflection; you must override the trailing echoes
            injection_delay_ms = spoof_tof * 1000.0
            status = "TAIL-GATE OVERRIDE MODE"
            
        return injection_delay_ms, status

# ==========================================
# SIMULATION EXECUTION INTERFACE
# ==========================================
if __name__ == "__main__":
    print("[*] SIGINT Trajectory Interceptor Core Online.")
    print("[*] Tracking dynamic boundaries... Press Ctrl+C to stop.\n")
    
    interceptor = TrajectoryInterceptor(target_distance_init=6.0, velocity=-0.8)
    
    try:
        for frame in range(1, 11):
            time.sleep(0.5)  # Wait for the next tracking pulse interval
            
            # 1. Track the moving trajectory
            predicted_tof = interceptor.track_and_predict_trajectory()
            real_distance = predicted_tof * interceptor.speed_of_sound
            
            # 2. Calculate the injection timing to project a fake 3.5-meter distance path
            delay, state = interceptor.calculate_injection_window(predicted_tof, spoof_distance=3.5)
            
            print(f"[Frame {frame:02d}] Real Target: {real_distance:.2f}m | Real ToF: {predicted_tof*1000:.2f}ms")
            print(f"         └──► Action: {state} | Fire Tx Pulse at exactly: {delay:.2f}ms past T0\n")
            
    except KeyboardInterrupt:
        print("[*] Interception routine halted.")
