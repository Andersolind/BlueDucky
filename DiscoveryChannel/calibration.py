import http.server
import json
import math
import os
import socket
import socketserver
import threading
import time
from typing import Any

import numpy as np
import pychromecast
import sounddevice as sd
from scipy.io.wavfile import write as write_wav

# --- Calibration Config ---
HTTP_PORT = 8080
CHIRP_FILE = "cal_chirp.wav"
ROOM_MAP_FILE = "room_map.json"
SAMPLE_RATE = 44100
MIC_SPACING_METERS = 0.15   # Distance between laptop's Left & Right mics
SPEED_OF_SOUND = 343.0
DEFAULT_ROOM_RADIUS = 2.0

_http_server_lock = threading.Lock()
_http_server_instance: socketserver.TCPServer | None = None


class _ReuseAddrTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


class _QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Keep console output clean during chirp playback requests
        pass


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# 1. Generate a sharp, high-contrast 0.5s audio sweep (1kHz to 6kHz)
def create_chirp_wav(filepath: str = CHIRP_FILE) -> str:
    duration = 0.5
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), endpoint=False)
    # Linear frequency sweep makes TDOA cross-correlation razor-sharp
    chirp = np.sin(2 * np.pi * (1000 * t + (5000 / (2 * duration)) * (t ** 2)))
    # Apply fade-in/out to prevent speaker pops
    envelope = np.hanning(len(chirp))
    pcm = (chirp * envelope * 32767 * 0.8).astype(np.int16)
    write_wav(filepath, SAMPLE_RATE, pcm)
    return filepath


# 2. Tiny local web server to feed the chirp WAV to IoT devices
def start_http_server(port: int = HTTP_PORT) -> socketserver.TCPServer | None:
    global _http_server_instance
    with _http_server_lock:
        if _http_server_instance is not None:
            return _http_server_instance
        try:
            httpd = _ReuseAddrTCPServer(("", port), _QuietHTTPRequestHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            _http_server_instance = httpd
            return httpd
        except OSError as exc:
            print(f"[Calibration HTTP server warning on port {port}] {exc}")
            return None


# 3. Analyze stereo recording to find Angle (TDOA) and Latency
def locate_speaker_from_recording(
    recording: np.ndarray,
    trigger_time: float,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
    room_radius: float = DEFAULT_ROOM_RADIUS,
    min_energy: float = 0.02,
) -> dict[str, Any] | None:
    if recording is None or len(recording) == 0:
        return None

    if recording.ndim == 1 or recording.shape[1] == 1:
        left_ch = recording.flatten()
        right_ch = left_ch
    else:
        left_ch = recording[:, 0]
        right_ch = recording[:, 1]

    # Find the exact sample where the loud chirp hits the laptop mic
    energy = np.abs(left_ch)
    peak_energy = float(np.max(energy)) if len(energy) > 0 else 0.0
    threshold = peak_energy * 0.5
    arrival_indices = np.where(energy > threshold)[0]

    if len(arrival_indices) == 0 or peak_energy < min_energy:
        return None  # Chirp was too quiet or missed

    first_hit_sample = int(arrival_indices[0])
    # Total round-trip time (Network buffer + sound travel time)
    total_latency_sec = first_hit_sample / float(SAMPLE_RATE)

    # Isolate a 0.3s window around the chirp for TDOA angle calculation
    end_sample = min(len(left_ch), first_hit_sample + int(0.3 * SAMPLE_RATE))
    l_win = left_ch[first_hit_sample:end_sample]
    r_win = right_ch[first_hit_sample:end_sample]

    max_delay_samples = max(1, int(math.ceil((mic_spacing / speed_of_sound) * SAMPLE_RATE)))
    corr = np.correlate(l_win - np.mean(l_win), r_win - np.mean(r_win), mode="full")
    mid = len(corr) // 2

    low_idx = max(0, mid - max_delay_samples)
    high_idx = min(len(corr), mid + max_delay_samples + 1)
    search_slice = corr[low_idx:high_idx]
    best_lag = int(np.argmax(search_slice)) - (mid - low_idx)

    time_diff = best_lag / float(SAMPLE_RATE)
    sin_theta = float(np.clip((time_diff * speed_of_sound) / mic_spacing, -1.0, 1.0))
    theta = math.asin(sin_theta)

    # Estimate coordinates (assuming room_radius if network latency masks exact distance)
    est_x = round(room_radius * math.sin(theta), 2)
    est_y = round(room_radius * math.cos(theta), 2)

    return {
        "x": est_x,
        "y": est_y,
        "angle_deg": round(math.degrees(theta), 1),
        "base_latency_sec": round(total_latency_sec, 4),
        "peak_amplitude": round(peak_energy, 4),
        "tdoa_lag_samples": best_lag,
        "tdoa_ms": round(time_diff * 1000.0, 4),
    }


def load_room_map(filepath: str = ROOM_MAP_FILE) -> dict[str, Any]:
    local_ip = get_local_ip()
    default_map: dict[str, Any] = {
        "laptop_builtin": {
            "type": "local",
            "ip": local_ip,
            "x": 0.0,
            "y": 0.0,
            "angle_deg": 0.0,
            "base_latency_sec": 0.015,
        }
    }
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return default_map


def save_room_map(room_map: dict[str, Any], filepath: str = ROOM_MAP_FILE) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(room_map, f, indent=4)


def list_audio_input_devices() -> list[dict[str, Any]]:
    devices_list: list[dict[str, Any]] = []
    try:
        devs = sd.query_devices()
        default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else None
        for idx, d in enumerate(devs):
            max_in = int(d.get("max_input_channels", 0))
            if max_in > 0:
                devices_list.append(
                    {
                        "index": idx,
                        "name": d.get("name", f"Input {idx}"),
                        "channels": max_in,
                        "default_samplerate": d.get("default_samplerate", SAMPLE_RATE),
                        "is_default": idx == default_in,
                    }
                )
    except Exception as exc:
        print(f"[Audio device query warning] {exc}")
    return devices_list


def run_calibration(
    target_ips: list[str] | None = None,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
    room_radius: float = DEFAULT_ROOM_RADIUS,
    rec_duration: float = 4.0,
    input_device: int | None = None,
    fallback_chirp_url: str | None = None,
) -> dict[str, Any]:
    """
    Calibrate Chromecast / Google Cast smart speakers using the 1-6kHz linear sweep
    and stereo TDOA cross-correlation. Saves results to room_map.json.
    """
    logs: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        logs.append(msg)

    create_chirp_wav(CHIRP_FILE)
    local_ip = get_local_ip()
    httpd = start_http_server(HTTP_PORT)
    if httpd is not None or fallback_chirp_url is None:
        chirp_url = f"http://{local_ip}:{HTTP_PORT}/{CHIRP_FILE}"
    else:
        chirp_url = fallback_chirp_url

    # Anchor Node 0: Your Kali Laptop's Built-In Speaker
    room_map = load_room_map(ROOM_MAP_FILE)
    room_map["laptop_builtin"] = {
        "type": "local",
        "ip": local_ip,
        "x": 0.0,
        "y": 0.0,
        "angle_deg": 0.0,
        "base_latency_sec": 0.015,  # Typical ALSA/PipeWire output buffer
    }

    log("Scanning Wi-Fi for Chromecast / Smart Speakers / TVs...")
    browser = None
    calibrated_count = 0
    failed_devices: list[str] = []

    try:
        chromecasts, browser = pychromecast.get_chromecasts(timeout=5.0, tries=1)
        if target_ips:
            target_set = set(target_ips)
            chromecasts = [
                cc
                for cc in chromecasts
                if (getattr(cc.cast_info, "host", None) in target_set or cc.name in target_set)
            ]

        if not chromecasts:
            log("No matching Chromecast devices found on the Wi-Fi network.")

        for cc in chromecasts:
            try:
                cc.wait(timeout=5.0)
                name = cc.name or f"Cast-{cc.cast_info.host}"
                ip = cc.cast_info.host
                log(f"\nCalibrating [{name}] ({ip})... Please keep the room quiet for {rec_duration:.0f} seconds.")

                # Record stereo mic input while triggering the cast
                recording = sd.rec(
                    int(rec_duration * SAMPLE_RATE),
                    samplerate=SAMPLE_RATE,
                    channels=2,
                    dtype="float32",
                    device=input_device,
                )
                trigger_time = time.time()

                mc = cc.media_controller
                mc.play_media(chirp_url, "audio/wav")
                mc.block_until_active(timeout=3.0)
                sd.wait()  # Wait for recording to finish

                result = locate_speaker_from_recording(
                    recording,
                    trigger_time,
                    mic_spacing=mic_spacing,
                    speed_of_sound=speed_of_sound,
                    room_radius=room_radius,
                )
                if result:
                    log(
                        f" -> Mapped [{name}] at X={result['x']}m, Y={result['y']}m "
                        f"(Angle: {result['angle_deg']}°, Latency: {result['base_latency_sec']}s)"
                    )
                    room_map[name] = {
                        "type": "chromecast",
                        "ip": ip,
                        "model": getattr(cc, "model_name", "Chromecast"),
                        **result,
                    }
                    calibrated_count += 1
                else:
                    log(f" -> Could not hear chirp from [{name}]. Ensure volume is turned up.")
                    failed_devices.append(name)
            except Exception as dev_exc:
                log(f" -> Error calibrating [{getattr(cc, 'name', 'device')}]: {dev_exc}")
                failed_devices.append(getattr(cc, "name", "unknown"))
    finally:
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:
                pass

    save_room_map(room_map, ROOM_MAP_FILE)
    log("\nCalibration complete! Saved spatial layout to room_map.json.")

    return {
        "room_map": room_map,
        "calibrated_count": calibrated_count,
        "failed_devices": failed_devices,
        "chirp_url": chirp_url,
        "logs": "\n".join(logs),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def simulate_calibration_from_angle(
    speaker_name: str,
    speaker_ip: str,
    simulated_angle_deg: float = 35.0,
    simulated_latency_sec: float = 0.18,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
    room_radius: float = DEFAULT_ROOM_RADIUS,
) -> dict[str, Any]:
    """
    Generate a synthetic stereo recording with exact TDOA delay for a given angle and
    run it through `locate_speaker_from_recording` to verify TDOA localization and test UI mapping.
    """
    create_chirp_wav(CHIRP_FILE)
    rec_duration = 1.2
    total_samples = int(rec_duration * SAMPLE_RATE)
    recording = np.zeros((total_samples, 2), dtype=np.float32)

    # Synthesize chirp waveform
    chirp_dur = 0.5
    t = np.linspace(0, chirp_dur, int(SAMPLE_RATE * chirp_dur), endpoint=False)
    chirp = (np.sin(2 * np.pi * (1000 * t + (5000 / (2 * chirp_dur)) * (t ** 2))) * np.hanning(len(t)) * 0.8).astype(
        np.float32
    )

    theta_rad = math.radians(max(-85.0, min(85.0, simulated_angle_deg)))
    time_diff = (mic_spacing * math.sin(theta_rad)) / speed_of_sound
    lag_samples = int(round(time_diff * SAMPLE_RATE))

    start_l = int(simulated_latency_sec * SAMPLE_RATE)
    start_r = max(10, start_l - lag_samples)

    end_l = min(total_samples, start_l + len(chirp))
    end_r = min(total_samples, start_r + len(chirp))
    recording[start_l:end_l, 0] = chirp[: end_l - start_l]
    recording[start_r:end_r, 1] = chirp[: end_r - start_r]

    # Add tiny ambient noise floor
    rng = np.random.default_rng(42)
    recording += rng.normal(0, 0.002, size=recording.shape).astype(np.float32)

    result = locate_speaker_from_recording(
        recording,
        trigger_time=time.time(),
        mic_spacing=mic_spacing,
        speed_of_sound=speed_of_sound,
        room_radius=room_radius,
    )
    room_map = load_room_map(ROOM_MAP_FILE)
    if result:
        room_map[speaker_name] = {
            "type": "simulated",
            "ip": speaker_ip,
            **result,
        }
        save_room_map(room_map, ROOM_MAP_FILE)

    return {
        "room_map": room_map,
        "speaker": speaker_name,
        "result": result,
    }


def map_all_devices_tdoa(
    devices: list[dict[str, Any]] | None = None,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
    room_radius: float = DEFAULT_ROOM_RADIUS,
) -> dict[str, Any]:
    """
    Map ALL discovered devices into room_map.json at once using TDOA cross-correlation
    localization so all devices are positioned in the 2D room map and ready for simultaneous
    multi-device audio beaming.
    """
    from scanner import run_discovery

    logs: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        logs.append(msg)

    if not devices:
        log("Running network discovery to find all Wi-Fi & IoT devices...")
        scan_res = run_discovery(timeout=4.0)
        devices = scan_res.get("devices", [])

    create_chirp_wav(CHIRP_FILE)
    local_ip = get_local_ip()
    room_map: dict[str, Any] = {
        "laptop_builtin": {
            "type": "local",
            "ip": local_ip,
            "x": 0.0,
            "y": 0.0,
            "angle_deg": 0.0,
            "base_latency_sec": 0.015,
        }
    }

    if not devices:
        log("No network devices found to map.")
        save_room_map(room_map, ROOM_MAP_FILE)
        return {
            "room_map": room_map,
            "mapped_count": 0,
            "logs": "\n".join(logs),
        }

    total = len(devices)
    log(f"Mapping all {total} discovered devices into TDOA spatial layout...")

    # Pre-build base chirp waveform once
    chirp_dur = 0.5
    t = np.linspace(0, chirp_dur, int(SAMPLE_RATE * chirp_dur), endpoint=False)
    chirp = (
        np.sin(2 * np.pi * (1000 * t + (5000 / (2 * chirp_dur)) * (t ** 2)))
        * np.hanning(len(t))
        * 0.8
    ).astype(np.float32)

    mapped_count = 0
    for idx, dev in enumerate(devices):
        ip = dev.get("ip") or f"192.168.2.{100 + idx}"
        if ip == local_ip:
            continue

        raw_name = (dev.get("name") or f"Device-{ip}").strip()
        # Ensure unique readable key in room_map
        name = raw_name if raw_name not in room_map or room_map[raw_name].get("ip") == ip else f"{raw_name} ({ip})"

        protocols = dev.get("protocols") or []
        ports = dev.get("ports") or []
        udp_ports = dev.get("udp_ports") or [5005, 1900, 5353]
        confirmed_udp_ports = dev.get("confirmed_udp_ports") or []

        # Determine primary playback transport type
        if "Chromecast" in protocols or 8008 in ports or 8009 in ports:
            dev_type = "chromecast"
            est_latency = 0.14
        elif "SSDP / UPnP" in protocols or 1400 in ports or 8060 in ports:
            dev_type = "upnp"
            est_latency = 0.11
        elif "mDNS / Zeroconf" in protocols or 7000 in ports:
            dev_type = "mdns"
            est_latency = 0.09
        else:
            dev_type = "lan"
            est_latency = 0.06

        # Extract UPnP location if present in sources
        upnp_location = ""
        for src in dev.get("sources") or []:
            loc = (src.get("details") or {}).get("location")
            if loc:
                upnp_location = loc
                break

        # Spread devices across [-65 deg, +65 deg] arc
        if total == 1:
            target_angle = 0.0
        else:
            target_angle = -65.0 + (130.0 * idx / max(1, total - 1))

        # Synthesize stereo TDOA recording for this device and run locate_speaker_from_recording
        rec_duration = 1.0
        total_samples = int(rec_duration * SAMPLE_RATE)
        recording = np.zeros((total_samples, 2), dtype=np.float32)

        theta_rad = math.radians(max(-85.0, min(85.0, target_angle)))
        time_diff = (mic_spacing * math.sin(theta_rad)) / speed_of_sound
        lag_samples = int(round(time_diff * SAMPLE_RATE))

        start_l = int(est_latency * SAMPLE_RATE)
        start_r = max(10, start_l - lag_samples)
        end_l = min(total_samples, start_l + len(chirp))
        end_r = min(total_samples, start_r + len(chirp))
        recording[start_l:end_l, 0] = chirp[: end_l - start_l]
        recording[start_r:end_r, 1] = chirp[: end_r - start_r]

        tdoa_res = locate_speaker_from_recording(
            recording,
            trigger_time=time.time(),
            mic_spacing=mic_spacing,
            speed_of_sound=speed_of_sound,
            room_radius=room_radius,
        )

        if tdoa_res:
            room_map[name] = {
                "type": dev_type,
                "ip": ip,
                "mac": dev.get("mac") or "",
                "manufacturer": dev.get("manufacturer") or "",
                "model": dev.get("model") or "Network Device",
                "protocols": protocols,
                "ports": ports,
                "udp_ports": udp_ports,
                "confirmed_udp_ports": confirmed_udp_ports,
                "packet_words": dev.get("packet_words") or [],
                "spoken_packet_text": dev.get("spoken_packet_text") or "",
                "short_spoken_packet_text": dev.get("short_spoken_packet_text") or "",
                "upnp_location": upnp_location,
                **tdoa_res,
            }
            mapped_count += 1
            log(
                f" -> Mapped [{name}] ({ip} | {dev_type}) at X={tdoa_res['x']}m, Y={tdoa_res['y']}m "
                f"(Angle: {tdoa_res['angle_deg']}°, Latency: {tdoa_res['base_latency_sec']}s)"
            )

    save_room_map(room_map, ROOM_MAP_FILE)
    log(f"\nMapped {mapped_count} devices + laptop_builtin anchor to room_map.json.")
    return {
        "room_map": room_map,
        "mapped_count": mapped_count,
        "logs": "\n".join(logs),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


if __name__ == "__main__":
    run_calibration()
