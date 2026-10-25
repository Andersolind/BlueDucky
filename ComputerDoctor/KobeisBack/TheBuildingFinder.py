import math

def haversine_distance(lat1, lon1, lat2, lon2):
    # Calculates the true distance over the earth's surface in km
    R = 6371.0 # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2)**2 + 
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def calculate_link_budget(dist_km, freq_ghz):
    # 1. Calculate Fresnel Zone Radius at midpoint (in metres)
    fresnel_r = 17.32 * math.sqrt(dist_km / (4 * freq_ghz))
    
    # 2. Calculate Earth Bulge at midpoint (in metres)
    # Formula: H = (d1 * d2) / (12.75 * K), assuming standard K-factor of 4/3
    earth_bulge = (dist_km / 2) ** 2 / 17.0
    
    # 3. Target beam width for 8 metres wide at the destination
    # Angle in degrees = 2 * arctan((width/2) / distance)
    beam_angle = 2 * math.atan2(4, dist_km * 1000) * (180 / math.pi)
    
    return fresnel_r, earth_bulge, beam_angle

# Coordinates
tx_lat, tx_lon = 43.6150, -79.6650          # Example Tx Location (Kali machine)
target_lat, target_lon = 43.6095564, -79.657226 # Your Target Location
freq_test = 0.915                           # 915 MHz ISM Band (0.915 GHz)

distance = haversine_distance(tx_lat, tx_lon, target_lat, target_lon)
f_radius, bulge, angle = calculate_link_budget(distance, freq_test)

print(f"=== GEOSPATIAL PATH ANALYSIS ===")
print(f"Distance to Target: {distance:.2f} km")
print(f"Earth Bulge Obstruction at Midpoint: {bulge:.2f} metres")
print(f"Fresnel Zone Clear Radius Needed: {f_radius:.2f} metres")
print(f"Total Structural Height Needed to clear flat earth: {bulge + f_radius:.2f} metres")
print(f"Required Antenna Beam Width for 8m target pocket: {angle:.4f}° degrees")
