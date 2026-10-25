import math
import time
import threading
import sqlite3
import csv
from xmlrpc.client import ServerProxy
import numpy as np

# --- SIMPLE 1D KALMAN FILTER FOR POSITION SMOOTHING ---
class GPSKalmanFilter:
    def __init__(self, process_variance=1e-5, measurement_variance=1e-3):
        self.q = process_variance  # How much the true position fluctuates
        self.r = measurement_variance  # Noise level of the GPS device sensor
        self.x = None              # Estimated true state coordinate
        self.p = 1.0               # Estimation error covariance matrix value

    def update(self, measurement):
        if self.x is None:
            self.x = measurement
            return self.x
        
        # Prediction Phase Step
        p_prior = self.p + self.q
        
        # Measurement Correction Phase Step (Gain calculation)
        kalman_gain = p_prior / (p_prior + self.r)
        self.x = self.x + kalman_gain * (measurement - self.x)
        self.p = (1.0 - kalman_gain) * p_prior
        
        return self.x

# --- MAIN SYSTEM ENGINE WITH EXPORTER ---
class PrecisionOperationsController:
    def __init__(self, gnuradio_rpc_port=8080):
        self.gr_control = ServerProxy(f"http://localhost:{gnuradio_rpc_port}/")
        
        # Base Station Geographic Origin
        self.base_lat = 43.5183
        self.base_lon = -79.8774
        self.base_alt = 150.0
        self.speed_of_light = 299792458.0
        
        # Hardware Configurations
        self.center_freq_hz = 915e6
        self.target_fm_nominal_hz = 98.1e6
        self.wavelength = self.speed_of_light / self.center_freq_hz
        self.element_spacing = self.wavelength / 2.0
        
        # Kinematics Memory State
        self.last_time = None
        self.last_range = None
        
        # Instantiating Independent Kalman Filters for Lat & Lon streams
        self.lat_filter = GPSKalmanFilter()
        self.lon_filter = GPSKalmanFilter()
        
        self.db_name = "network_operations.db"
        self.init_database()
        self.is_tracking = False

    def init_database(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spatial_telemetry_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                latitude REAL,
                longitude REAL,
                range_meters REAL,
                bearing_deg REAL,
                doppler_shift_hz REAL,
                tuned_freq_hz REAL,
                phase_weights_complex TEXT
            )
        """)
        conn.commit()
        conn.close()

    def log_operation_entry(self, lat, lon, r_meters, bearing, doppler, tuned_f, weights):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        weights_str = ",".join([f"{w.real:.4f}+{w.imag:.4f}j" for w in weights])
        cursor.execute("""
            INSERT INTO spatial_telemetry_audit 
            (timestamp, latitude, longitude, range_meters, bearing_deg, doppler_shift_hz, tuned_freq_hz, phase_weights_complex)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (time.strftime("%Y-%m-%d %H:%M:%S"), lat, lon, r_meters, bearing, doppler, tuned_f, weights_str))
        conn.commit()
        conn.close()

    def export_database_to_csv(self, output_filename="telemetry_export.csv"):
        """ Drops the complete SQLite log history cleanly out into an external CSV spreadsheet """
        print(f"\n[*] Exporting database records to file: {output_filename}...")
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM spatial_telemetry_audit")
            rows = cursor.fetchall()
            
            # Fetch structured column titles from schema definition
            column_names = [description[0] for description in cursor.description]
            
            with open(output_filename, mode='w', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(column_names)  # Write table header row
                writer.writerows(rows)         # Write data payload blocks
                
            conn.close()
            print(f"[SUCCESS] CSV Export completed. {len(rows)} operational logs saved safely.")
        except Exception as e:
            print(f"[!] Critical Error dumping data to CSV file: {e}")

    def calculate_vectors_and_doppler(self, current_lat, current_lon):
        current_time = time.time()
        lat1, lon1 = math.radians(self.base_lat), math.radians(self.base_lon)
        lat2, lon2 = math.radians(current_lat), math.radians(current_lon)
        
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance_meters = 6371000.0 * c 
        
        y = math.sin(dlon) * math.cos(lat2)
        x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
        bearing_rad = math.atan2(y, x)
        bearing_deg = math.degrees(bearing_rad) % 360
        
        doppler_shift_hz = 0.0
        if self.last_range is not None and self.last_time is not None:
            delta_time = current_time - self.last_time
            if delta_time > 0:
                radial_velocity_ms = (distance_meters - self.last_range) / delta_time
                doppler_shift_hz = -(radial_velocity_ms / self.speed_of_light) * self.target_fm_nominal_hz

        self.last_time = current_time
        self.last_range = distance_meters
        
        return distance_meters, bearing_rad, bearing_deg, doppler_shift_hz

    def process_telemetry_update(self, raw_lat, raw_lon):
        # 1. Feed jittery raw coordinates through the Kalman filter models first
        filtered_lat = self.lat_filter.update(raw_lat)
        filtered_lon = self.lon_filter.update(raw_lon)
        
        # 2. Run physical kinematics math blocks using the clean, filtered coordinates
        distance, bearing_rad, bearing_deg, doppler_hz = self.calculate_vectors_and_doppler(filtered_lat, filtered_lon)
        
        k = (2 * math.pi) / self.wavelength
        phase_weights = [np.exp(1j * idx * k * self.element_spacing * math.sin(bearing_rad)) for idx in range(4)]
        compensated_fm_frequency = int(self.target_fm_nominal_hz + doppler_hz)
        
        print(f"[KALMAN LOCK] Cleaned Lat: {filtered_lat:.6f} | Cleaned Lon: {filtered_lon:.6f}")
        print(f"              Tuning: {compensated_fm_frequency/1e6:.6f} MHz | Doppler Shift: {doppler_hz:+.2f} Hz")
        
        try:
            self.gr_control.set_center_freq(compensated_fm_frequency)
            self.gr_control.set_weight_0(complex(phase_weights[0]))
            self.gr_control.set_weight_1(complex(phase_weights[1]))
            self.gr_control.set_weight_2(complex(phase_weights[2]))
            self.gr_control.set_weight_3(complex(phase_weights[3]))
        except Exception as e:
            print(f"[!] GRC Communication Window Offline. Is flowgraph active? ({e})")
            
        self.log_operation_entry(filtered_lat, filtered_lon, distance, bearing_deg, doppler_hz, compensated_fm_frequency, phase_weights)

    def run_tracking_scenario(self):
        self.is_tracking = True
        print("[*] Kalman Filtering, Logging, and Export Subsystems Active.\n")
        
        # Your target base location parameters
        start_lat = 43.491826 
        start_lon = -79.835807
        
        print("[*] Simulating tracking data updates with simulated GPS receiver noise...")
        simulated_route_offsets = np.linspace(0.0, 0.005, 10)
        
        for offset in simulated_route_offsets:
            if not self.is_tracking: break
            
            # Introduce high structural variance noise to simulate typical GPS error spikes
            gps_sensor_noise_lat = np.random.normal(0, 0.0002)
            gps_sensor_noise_lon = np.random.normal(0, 0.0002)
            
            noisy_lat = start_lat + gps_sensor_noise_lat
            noisy_lon = (start_lon + offset) + gps_sensor_noise_lon
            
            self.process_telemetry_update(noisy_lat, noisy_lon)
            time.sleep(2.0)

    def stop(self):
        self.is_tracking = False
        # Dump logs immediately upon closing down operations
        self.export_database_to_csv()

if __name__ == "__main__":
    controller = PrecisionOperationsController()
    try:
        controller.run_tracking_scenario()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
        print("[+] Hardware tracking pipeline closed safely.")
