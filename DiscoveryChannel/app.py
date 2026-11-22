import argparse
import os
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_file

from beamformer import (
    AVAILABLE_VOICES,
    BASE_WAV,
    dispatch_sum_difference_tts,
    generate_tts_wav,
    list_ollama_models,
    ollama_generate_and_beam,
    probe_and_update_active_udp_ports,
    speak_iot_packets_and_mic_listen,
    udp_reflector,
    voice_listener,
)
from calibration import (
    CHIRP_FILE,
    DEFAULT_ROOM_RADIUS,
    HTTP_PORT,
    MIC_SPACING_METERS,
    ROOM_MAP_FILE,
    SPEED_OF_SOUND,
    create_chirp_wav,
    list_audio_input_devices,
    load_room_map,
    map_all_devices_tdoa,
    run_calibration,
    save_room_map,
    simulate_calibration_from_angle,
)
from scanner import get_local_ip_and_subnet, run_discovery

app = Flask(__name__)

# In-memory cache of the most recent scan result
_last_scan: dict[str, Any] | None = None


@app.errorhandler(Exception)
def handle_api_exception(exc: Exception):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(exc), "logs": f"Error: {exc}"}), 500
    raise exc


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/cal_chirp.wav")
def serve_chirp_wav():
    if not os.path.exists(CHIRP_FILE):
        create_chirp_wav(CHIRP_FILE)
    return send_file(os.path.abspath(CHIRP_FILE), mimetype="audio/wav")


@app.route("/audio/<path:filename>")
def serve_generated_audio(filename: str):
    # Only allow safe wav files in working directory
    safe_name = os.path.basename(filename)
    if not safe_name.endswith(".wav") or not (
        safe_name.startswith("beam_") or safe_name in (BASE_WAV, CHIRP_FILE)
    ):
        abort(404)
    full_path = os.path.abspath(safe_name)
    if not os.path.isfile(full_path):
        abort(404)
    return send_file(full_path, mimetype="audio/wav")


@app.route("/api/status", methods=["GET"])
def api_status():
    local_ip, subnet = get_local_ip_and_subnet()
    return jsonify(
        {
            "local_ip": local_ip,
            "subnet": str(subnet),
            "last_scan": _last_scan,
            "room_map": load_room_map(ROOM_MAP_FILE),
            "audio_devices": list_audio_input_devices(),
            "voices": AVAILABLE_VOICES,
            "voice_listener": voice_listener.status(),
            "udp_reflector": udp_reflector.status(),
            "ollama": list_ollama_models(),
            "calibration_defaults": {
                "mic_spacing": MIC_SPACING_METERS,
                "speed_of_sound": SPEED_OF_SOUND,
                "room_radius": DEFAULT_ROOM_RADIUS,
                "http_port": HTTP_PORT,
            },
        }
    )


@app.route("/api/scan", methods=["POST"])
def api_scan():
    global _last_scan
    payload = request.get_json(silent=True) or {}
    methods = payload.get("methods") or ["chromecast", "ssdp", "mdns", "arp", "udp_nmap"]
    timeout = float(payload.get("timeout", 4.5))
    timeout = max(1.5, min(timeout, 15.0))

    result = run_discovery(methods=methods, timeout=timeout)

    console_lines = ["Scanning Wi-Fi for smart speakers, TVs, and active UDP multicast responders..."]
    for dev in result["devices"]:
        udp_list = dev.get("confirmed_udp_ports") or dev.get("udp_ports") or []
        udp_str = f" | Active UDP: {udp_list}" if udp_list else ""
        console_lines.append(
            f"Found IoT Device: {dev['name']} | IP: {dev['ip']} | Model: {dev['model']}{udp_str}"
        )
    if not result["devices"]:
        console_lines.append("No devices found matching the selected discovery protocols.")
    result["console_output"] = "\n".join(console_lines)

    _last_scan = result
    return jsonify(result)


@app.route("/api/room-map", methods=["GET"])
def api_get_room_map():
    return jsonify({"room_map": load_room_map(ROOM_MAP_FILE)})


@app.route("/api/room-map/reset", methods=["POST"])
def api_reset_room_map():
    local_ip, _ = get_local_ip_and_subnet()
    fresh = {
        "laptop_builtin": {
            "type": "local",
            "ip": local_ip,
            "x": 0.0,
            "y": 0.0,
            "angle_deg": 0.0,
            "base_latency_sec": 0.015,
        }
    }
    save_room_map(fresh, ROOM_MAP_FILE)
    return jsonify({"room_map": fresh})


@app.route("/api/calibrate", methods=["POST"])
def api_calibrate():
    payload = request.get_json(silent=True) or {}
    target_ips = payload.get("target_ips")
    mic_spacing = float(payload.get("mic_spacing", MIC_SPACING_METERS))
    speed_of_sound = float(payload.get("speed_of_sound", SPEED_OF_SOUND))
    room_radius = float(payload.get("room_radius", DEFAULT_ROOM_RADIUS))
    rec_duration = float(payload.get("rec_duration", 4.0))
    input_device = payload.get("input_device")
    if input_device is not None and input_device != "":
        input_device = int(input_device)
    else:
        input_device = None

    local_ip, _ = get_local_ip_and_subnet()
    fallback_url = f"http://{local_ip}:{request.host.split(':')[-1] if ':' in request.host else '5000'}/cal_chirp.wav"

    res = run_calibration(
        target_ips=target_ips,
        mic_spacing=mic_spacing,
        speed_of_sound=speed_of_sound,
        room_radius=room_radius,
        rec_duration=rec_duration,
        input_device=input_device,
        fallback_chirp_url=fallback_url,
    )
    return jsonify(res)


@app.route("/api/calibrate/simulate", methods=["POST"])
def api_calibrate_simulate():
    payload = request.get_json(silent=True) or {}
    speaker_name = (payload.get("speaker_name") or "Simulated Cast Speaker").strip()
    speaker_ip = (payload.get("speaker_ip") or "192.168.1.100").strip()
    angle_deg = float(payload.get("angle_deg", 30.0))
    latency_sec = float(payload.get("latency_sec", 0.16))
    mic_spacing = float(payload.get("mic_spacing", MIC_SPACING_METERS))
    speed_of_sound = float(payload.get("speed_of_sound", SPEED_OF_SOUND))
    room_radius = float(payload.get("room_radius", DEFAULT_ROOM_RADIUS))

    res = simulate_calibration_from_angle(
        speaker_name=speaker_name,
        speaker_ip=speaker_ip,
        simulated_angle_deg=angle_deg,
        simulated_latency_sec=latency_sec,
        mic_spacing=mic_spacing,
        speed_of_sound=speed_of_sound,
        room_radius=room_radius,
    )
    return jsonify(res)


@app.route("/api/calibrate/map-all", methods=["POST"])
def api_calibrate_map_all():
    payload = request.get_json(silent=True) or {}
    devices = payload.get("devices")
    if not devices and _last_scan:
        devices = _last_scan.get("devices", [])
    mic_spacing = float(payload.get("mic_spacing", MIC_SPACING_METERS))
    speed_of_sound = float(payload.get("speed_of_sound", SPEED_OF_SOUND))
    room_radius = float(payload.get("room_radius", DEFAULT_ROOM_RADIUS))

    res = map_all_devices_tdoa(
        devices=devices,
        mic_spacing=mic_spacing,
        speed_of_sound=speed_of_sound,
        room_radius=room_radius,
    )
    return jsonify(res)


@app.route("/api/tts/beam", methods=["POST"])
def api_tts_beam():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "Hello World").strip() or "Hello World"
    listener_x = float(payload.get("listener_x", 0.0))
    listener_y = float(payload.get("listener_y", 1.5))
    voice = str(payload.get("voice", "en-us"))
    speed = int(payload.get("speed", 150))
    pitch = int(payload.get("pitch", 50))
    play_local = bool(payload.get("play_local", True))
    cast_enabled = bool(payload.get("cast_enabled", True))
    udp_enabled = bool(payload.get("udp_enabled", True))
    diff_gain = float(payload.get("diff_gain", -0.6))
    beam_mode = str(payload.get("beam_mode", "all_sum"))
    auto_map_all = bool(payload.get("auto_map_all", False))
    scan_active_udp = bool(payload.get("scan_active_udp", True))
    return_to_origin = bool(payload.get("return_to_origin", True))
    listen_with_mic = bool(payload.get("listen_with_mic", True))
    input_device = payload.get("input_device")
    if input_device is not None and input_device != "":
        input_device = int(input_device)
    else:
        input_device = None

    room_map = load_room_map(ROOM_MAP_FILE)
    if auto_map_all or len(room_map) <= 1:
        devices = (_last_scan or {}).get("devices")
        if devices:
            mapped = map_all_devices_tdoa(devices=devices)
            room_map = mapped["room_map"]

    res = dispatch_sum_difference_tts(
        text=text,
        listener_x=listener_x,
        listener_y=listener_y,
        room_map=room_map,
        voice=voice,
        speed=speed,
        pitch=pitch,
        play_local=play_local,
        cast_enabled=cast_enabled,
        udp_enabled=udp_enabled,
        blocking_local=False,
        diff_gain=diff_gain,
        beam_mode=beam_mode,
        scan_active_udp=scan_active_udp,
        return_to_origin=return_to_origin,
        listen_with_mic=listen_with_mic,
        input_device=input_device,
    )
    res["room_map"] = room_map
    res["udp_reflector"] = udp_reflector.status()
    return jsonify(res)


@app.route("/api/tts/speak-packets", methods=["POST"])
def api_tts_speak_packets():
    payload = request.get_json(silent=True) or {}
    target_device = payload.get("target_device") or None
    listener_x = float(payload.get("listener_x", 0.0))
    listener_y = float(payload.get("listener_y", 1.5))
    voice = str(payload.get("voice", "en-us"))
    speed = int(payload.get("speed", 165))
    pitch = int(payload.get("pitch", 50))
    play_local = bool(payload.get("play_local", True))
    listen_with_mic = bool(payload.get("listen_with_mic", True))
    udp_enabled = bool(payload.get("udp_enabled", True))
    return_to_origin = bool(payload.get("return_to_origin", True))
    use_ollama = bool(payload.get("use_ollama", True))
    ollama_model = payload.get("ollama_model") or None
    input_device = payload.get("input_device")
    if input_device is not None and input_device != "":
        input_device = int(input_device)
    else:
        input_device = None

    room_map = load_room_map(ROOM_MAP_FILE)
    if len(room_map) <= 1:
        devices = (_last_scan or {}).get("devices")
        if not devices:
            scan_res = run_discovery(timeout=3.5)
            devices = scan_res.get("devices", [])
        if devices:
            mapped = map_all_devices_tdoa(devices=devices)
            room_map = mapped["room_map"]

    res = speak_iot_packets_and_mic_listen(
        room_map=room_map,
        target_device=target_device,
        listener_x=listener_x,
        listener_y=listener_y,
        voice=voice,
        speed=speed,
        pitch=pitch,
        play_local=play_local,
        listen_with_mic=listen_with_mic,
        input_device=input_device,
        udp_enabled=udp_enabled,
        return_to_origin=return_to_origin,
        use_ollama=use_ollama,
        ollama_model=ollama_model,
    )
    res["udp_reflector"] = udp_reflector.status()
    return jsonify(res)


@app.route("/api/ollama/models", methods=["GET"])
def api_ollama_models():
    return jsonify(list_ollama_models())


@app.route("/api/ollama/beam", methods=["POST"])
def api_ollama_beam():
    payload = request.get_json(silent=True) or {}
    prompt = str(payload.get("prompt") or "").strip()
    model = payload.get("ollama_model") or payload.get("model") or None
    listener_x = float(payload.get("listener_x", 0.0))
    listener_y = float(payload.get("listener_y", 1.5))
    voice = str(payload.get("voice", "en-us"))
    speed = int(payload.get("speed", 155))
    pitch = int(payload.get("pitch", 50))
    play_local = bool(payload.get("play_local", True))
    cast_enabled = bool(payload.get("cast_enabled", True))
    udp_enabled = bool(payload.get("udp_enabled", True))
    beam_mode = str(payload.get("beam_mode", "all_sum"))
    listen_with_mic = bool(payload.get("listen_with_mic", True))
    input_device = payload.get("input_device")
    if input_device is not None and input_device != "":
        input_device = int(input_device)
    else:
        input_device = None

    room_map = load_room_map(ROOM_MAP_FILE)
    if len(room_map) <= 1:
        devices = (_last_scan or {}).get("devices")
        if devices:
            mapped = map_all_devices_tdoa(devices=devices)
            room_map = mapped["room_map"]

    res = ollama_generate_and_beam(
        prompt=prompt,
        model=model,
        room_map=room_map,
        listener_x=listener_x,
        listener_y=listener_y,
        voice=voice,
        speed=speed,
        pitch=pitch,
        play_local=play_local,
        cast_enabled=cast_enabled,
        udp_enabled=udp_enabled,
        beam_mode=beam_mode,
        listen_with_mic=listen_with_mic,
        input_device=input_device,
    )
    res["room_map"] = room_map
    res["udp_reflector"] = udp_reflector.status()
    return jsonify(res)


@app.route("/api/udp/scan", methods=["POST"])
def api_udp_scan():
    payload = request.get_json(silent=True) or {}
    listener_x = float(payload.get("listener_x", 0.0))
    listener_y = float(payload.get("listener_y", 1.5))
    timeout = float(payload.get("timeout", 3.5))

    room_map = load_room_map(ROOM_MAP_FILE)
    res = probe_and_update_active_udp_ports(
        room_map=room_map,
        listener_x=listener_x,
        listener_y=listener_y,
        timeout=timeout,
        run_nmap=True,
    )
    res["udp_reflector"] = udp_reflector.status()
    return jsonify(res)


@app.route("/api/udp/reflector/status", methods=["GET"])
def api_udp_reflector_status():
    return jsonify(udp_reflector.status())


@app.route("/api/udp/reflector/start", methods=["POST"])
def api_udp_reflector_start():
    payload = request.get_json(silent=True) or {}
    orig_x = float(payload.get("listener_x", 0.0))
    orig_y = float(payload.get("listener_y", 1.5))
    return jsonify(udp_reflector.start(orig_x=orig_x, orig_y=orig_y))


@app.route("/api/udp/reflector/stop", methods=["POST"])
def api_udp_reflector_stop():
    return jsonify(udp_reflector.stop())


@app.route("/api/tts/listener/status", methods=["GET"])
def api_tts_listener_status():
    return jsonify(voice_listener.status())


@app.route("/api/tts/listener/start", methods=["POST"])
def api_tts_listener_start():
    payload = request.get_json(silent=True) or {}
    reply_text = (payload.get("reply_text") or "Hello World").strip()
    voice = str(payload.get("voice", "en-us"))
    speed = int(payload.get("speed", 150))
    pitch = int(payload.get("pitch", 50))
    listener_y = float(payload.get("listener_y", 1.5))
    status = voice_listener.start(
        reply_text=reply_text,
        voice=voice,
        speed=speed,
        pitch=pitch,
        listener_y=listener_y,
    )
    return jsonify(status)


@app.route("/api/tts/listener/stop", methods=["POST"])
def api_tts_listener_stop():
    return jsonify(voice_listener.stop())


def run_cli(
    methods: list[str],
    timeout: float,
    calibrate: bool = False,
    speak_text: str | None = None,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    udp_scan: bool = False,
) -> None:
    if calibrate:
        run_calibration()
        return

    if udp_scan:
        probe_and_update_active_udp_ports(listener_x=listener_x, listener_y=listener_y, timeout=timeout)
        return

    if speak_text is not None:
        dispatch_sum_difference_tts(
            text=speak_text,
            listener_x=listener_x,
            listener_y=listener_y,
            play_local=True,
            cast_enabled=True,
            udp_enabled=True,
            blocking_local=True,
            scan_active_udp=True,
            return_to_origin=True,
        )
        return

    result = run_discovery(methods=methods, timeout=timeout)
    print("\n" + "=" * 72)
    print(f"DiscoveryChannel Scan Complete ({result['elapsed_seconds']}s on {result['subnet']})")
    print("=" * 72)
    for dev in result["devices"]:
        protos = ", ".join(dev["protocols"])
        udp_ports = dev.get("confirmed_udp_ports") or dev.get("udp_ports") or []
        print(
            f"Found IoT Device: {dev['name']} | IP: {dev['ip']} | Model: {dev['model']} | "
            f"Protocols: [{protos}] | Active UDP: {udp_ports}"
        )
    if not result["devices"]:
        print("No devices discovered.")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DiscoveryChannel - Wi-Fi IoT Scanner, TDOA Calibrator & Text-to-Audio Beamformer"
    )
    parser.add_argument("--cli", action="store_true", help="Run a one-shot discovery scan in the terminal and exit")
    parser.add_argument("--calibrate", action="store_true", help="Run acoustic TDOA room calibration in CLI mode")
    parser.add_argument("--udp-scan", action="store_true", help="Send multicast wake-up, run nmap -sU on active UDP ports, and echo to original position")
    parser.add_argument("--speak", type=str, default=None, help="Synthesize any text to audio and beam to room speakers")
    parser.add_argument("--x", type=float, default=0.0, help="Target listener X in meters for --speak (default: 0.0)")
    parser.add_argument("--y", type=float, default=1.5, help="Target listener Y in meters for --speak (default: 1.5)")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind web server (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Port for web dashboard (default: 5000)")
    parser.add_argument("--timeout", type=float, default=4.5, help="Scan timeout in seconds (default: 4.5)")
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["chromecast", "ssdp", "mdns", "arp", "udp_nmap"],
        choices=["chromecast", "ssdp", "mdns", "arp", "udp_nmap"],
        help="Discovery protocols to enable",
    )
    args = parser.parse_args()

    if args.cli or args.calibrate or args.udp_scan or args.speak is not None:
        run_cli(
            args.methods,
            args.timeout,
            calibrate=args.calibrate,
            speak_text=args.speak,
            listener_x=args.x,
            listener_y=args.y,
            udp_scan=args.udp_scan,
        )
    else:
        local_ip, subnet = get_local_ip_and_subnet()
        print(f"Starting DiscoveryChannel Vue + Python Dashboard on http://127.0.0.1:{args.port}")
        print(f"Detected local network: {local_ip} ({subnet})")
        app.run(host=args.host, port=args.port, debug=False)
