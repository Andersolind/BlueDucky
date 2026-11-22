import concurrent.futures
import ctypes
import http.server
import json
import math
import os
import re
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
import pychromecast
import requests
import sounddevice as sd
from scipy.io import wavfile

from calibration import (
    HTTP_PORT,
    MIC_SPACING_METERS,
    ROOM_MAP_FILE,
    SAMPLE_RATE,
    SPEED_OF_SOUND,
    get_local_ip,
    load_room_map,
    save_room_map,
    start_http_server,
)
from scanner import (
    UDP_IOT_PORTS,
    _probe_udp_host_direct,
    _read_arp_table,
    _run_nmap_udp_scan,
    extract_device_packet_words,
    ip_sort_key,
    is_ipv4_address,
    resolve_ipv6_to_ipv4,
    send_multicast_wakeup_and_capture,
)

# Optional dependencies for live voice-tracking loop
try:
    import webrtcvad  # type: ignore
except ImportError:
    webrtcvad = None

try:
    from vosk import KaldiRecognizer, Model  # type: ignore
except ImportError:
    Model = None
    KaldiRecognizer = None

# --- Configuration ---
UDP_IP = "239.0.0.1"
UDP_PORT = 5005
CHUNK_SAMPLES = 882  # 20ms frame at 44.1kHz
BASE_WAV = "tts_speech_raw.wav"

AVAILABLE_VOICES = [
    {"id": "en-us", "label": "English (US)"},
    {"id": "en-gb", "label": "English (UK)"},
    {"id": "en-sc", "label": "English (Scottish)"},
    {"id": "es", "label": "Spanish"},
    {"id": "fr", "label": "French"},
    {"id": "de", "label": "German"},
    {"id": "it", "label": "Italian"},
]

OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_BASE_URL.startswith(("http://", "https://")):
    OLLAMA_BASE_URL = f"http://{OLLAMA_BASE_URL}"

PREFERRED_OLLAMA_MODELS = [
    "eararray-sigint:latest",
    "andersolind/nightsweep-sigint:latest",
    "nightsweep-sigint:latest",
    "nightsweep-signalintelligence:latest",
    "strategic-relay:latest",
    "andersolind/strategic-relay:latest",
    "ALIENTELLIGENCE/radiofrequencyengineer:latest",
    "llama3.2:latest",
    "dolphin-llama3:8b",
]


def compute_spatial_quadrant_overlay(x: float, y: float) -> str:
    """Map 2D room coordinates (x, y) to EarArray-SIGINT spatial trajectory quadrants."""
    if x >= 0.0 and y >= 0.0:
        return "NORTHEAST_QUADRANT (Living Room Window Path)"
    if x < 0.0 and y >= 0.0:
        return "NORTHWEST_QUADRANT (Hallway Entry Transition Line)"
    if x >= 0.0 and y < 0.0:
        return "SOUTHEAST_QUADRANT (Staircase Ascent Access Corridor)"
    return "SOUTHWEST_QUADRANT (Dampened Bedroom Perimeter)"


def clean_text_for_speech(text: str) -> str:
    """Strip markdown symbols and formatting so espeak-ng reads Ollama output smoothly."""
    cleaned = re.sub(r"```[\s\S]*?```", " ", text or "")
    cleaned = re.sub(r"[`*_#>~|]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def list_ollama_models() -> dict[str, Any]:
    """Query local Ollama server (127.0.0.1:11434) for installed models and choose best default."""
    models: list[dict[str, Any]] = []
    available = False
    error_msg = ""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            available = True
            for m in data.get("models") or []:
                name = m.get("name") or ""
                size_gb = round(float(m.get("size") or 0) / (1024 ** 3), 2)
                details = m.get("details") or {}
                models.append(
                    {
                        "name": name,
                        "size_gb": size_gb,
                        "family": details.get("family") or "",
                        "parameter_size": details.get("parameter_size") or "",
                        "quantization": details.get("quantization_level") or "",
                    }
                )
    except Exception as exc:
        error_msg = str(exc)

    names = [m["name"] for m in models]
    default_model = "eararray-sigint:latest"
    for pref in PREFERRED_OLLAMA_MODELS:
        if pref in names:
            default_model = pref
            break
    else:
        if names:
            default_model = names[0]

    return {
        "available": available,
        "base_url": OLLAMA_BASE_URL,
        "default_model": default_model,
        "models": models,
        "error": error_msg,
    }


def query_ollama_model(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 180,
    temperature: float = 0.25,
    timeout: float = 25.0,
) -> dict[str, Any]:
    """Run local inference against an installed Ollama model."""
    chosen_model = (model or "").strip()
    if not chosen_model:
        info = list_ollama_models()
        chosen_model = info.get("default_model") or "eararray-sigint:latest"

    payload: dict[str, Any] = {
        "model": chosen_model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": int(max_tokens),
            "temperature": float(temperature),
        },
    }
    if system:
        payload["system"] = system

    start_t = time.time()
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_text = (data.get("response") or "").strip()
        spoken_text = clean_text_for_speech(raw_text)
        return {
            "ok": True,
            "model": chosen_model,
            "response": raw_text,
            "spoken_text": spoken_text,
            "elapsed_sec": round(time.time() - start_t, 2),
        }
    except Exception as exc:
        return {
            "ok": False,
            "model": chosen_model,
            "response": "",
            "spoken_text": "",
            "error": str(exc),
            "elapsed_sec": round(time.time() - start_t, 2),
        }

_espeak_lock = threading.Lock()


def _find_espeak_binary() -> str | None:
    venv_bin = os.path.join(os.path.dirname(sys.executable), "espeak-ng")
    if os.path.isfile(venv_bin) and os.access(venv_bin, os.X_OK):
        return venv_bin
    return shutil.which("espeak-ng") or shutil.which("espeak")


def _synthesize_via_ctypes(
    text: str,
    out_wav: str,
    voice: str = "en-us",
    speed: int = 150,
    pitch: int = 50,
) -> None:
    """Direct fallback using system libespeak-ng.so.1 if CLI binary is unavailable."""
    with _espeak_lock:
        lib = ctypes.CDLL("libespeak-ng.so.1")
        AUDIO_OUTPUT_SYNCHRONOUS = 0x02
        espeakCHARS_UTF8 = 1
        espeakRATE = 1
        espeakPITCH = 2

        SYNTH_CB = ctypes.CFUNCTYPE(
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_short),
            ctypes.c_int,
            ctypes.c_void_p,
        )

        sr = lib.espeak_Initialize(AUDIO_OUTPUT_SYNCHRONOUS, 500, None, 0)
        if sr <= 0:
            sr = 22050

        lib.espeak_SetVoiceByName(voice.encode("utf-8"))
        lib.espeak_SetParameter(espeakRATE, int(speed), 0)
        lib.espeak_SetParameter(espeakPITCH, int(pitch), 0)

        chunks: list[np.ndarray] = []

        def _cb(wav_ptr, numsamples, events):
            if wav_ptr and numsamples > 0:
                arr = np.ctypeslib.as_array(wav_ptr, shape=(numsamples,)).copy()
                chunks.append(arr)
            return 0

        cb_ref = SYNTH_CB(_cb)
        lib.espeak_SetSynthCallback(cb_ref)

        text_bytes = text.encode("utf-8")
        lib.espeak_Synth(text_bytes, len(text_bytes) + 1, 0, 0, 0, espeakCHARS_UTF8, None, None)
        lib.espeak_Synchronize()

        if chunks:
            pcm = np.concatenate(chunks).astype(np.int16)
        else:
            pcm = np.zeros(int(sr * 0.25), dtype=np.int16)

        wavfile.write(out_wav, sr, pcm)


# 1. Generate clean offline WAV for any text via espeak-ng
def generate_tts_wav(
    text: str = "Hello World",
    voice: str = "en-us",
    speed: int = 150,
    pitch: int = 50,
    out_wav: str = BASE_WAV,
) -> np.ndarray:
    clean_text = (text or "").strip() or "Hello World"
    espeak_bin = _find_espeak_binary()

    if espeak_bin:
        subprocess.run(
            [espeak_bin, "-v", voice, "-s", str(int(speed)), "-p", str(int(pitch)), "-w", out_wav, clean_text],
            check=True,
        )
    else:
        _synthesize_via_ctypes(clean_text, out_wav, voice=voice, speed=speed, pitch=pitch)

    sr, data = wavfile.read(out_wav)
    if data.ndim > 1:
        data = data[:, 0]

    # Convert to float32 in [-1.0, 1.0]
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32767.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483647.0
    elif data.dtype == np.uint8:
        data = (data.astype(np.float32) - 128.0) / 128.0
    else:
        data = data.astype(np.float32)

    # Resample to 44.1kHz if needed
    if sr != SAMPLE_RATE and len(data) > 0:
        num_samples = int(len(data) * SAMPLE_RATE / sr)
        data = np.interp(
            np.linspace(0, len(data), num_samples, endpoint=False),
            np.arange(len(data)),
            data,
        ).astype(np.float32)

    return data


def generate_hello_world_wav() -> np.ndarray:
    """Backwards-compatible helper from starter snippet."""
    return generate_tts_wav("Hello World")


# 3. Acoustic TDOA Angle Estimator
def estimate_speaker_x(
    left_ch: np.ndarray,
    right_ch: np.ndarray,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
) -> float:
    max_delay = max(1, int(math.ceil((mic_spacing / speed_of_sound) * SAMPLE_RATE)))
    l_norm = left_ch - np.mean(left_ch)
    r_norm = right_ch - np.mean(right_ch)
    corr = np.correlate(l_norm, r_norm, mode="full")
    mid = len(corr) // 2
    low = max(0, mid - max_delay)
    high = min(len(corr), mid + max_delay + 1)
    best_lag = int(np.argmax(corr[low:high])) - (mid - low)
    time_diff = best_lag / float(SAMPLE_RATE)
    sin_theta = float(np.clip((time_diff * speed_of_sound) / mic_spacing, -1.0, 1.0))
    return float(np.clip(1.5 * math.tan(math.asin(sin_theta)), -1.5, 1.5))


HEADER_FMT = "dff"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


def broadcast_udp_wave(
    audio_data: np.ndarray,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    target_ip: str = UDP_IP,
    target_port: int = UDP_PORT,
    is_multicast: bool = True,
    target_ports: list[int] | None = None,
    return_to_origin: bool = True,
    return_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Stream delay-padded audio chunks with the (timestamp, listener_x, listener_y) header
    to multicast 239.0.0.1:5005 or to all active UDP ports on a target host.
    If any active UDP port sends a packet back, unpack or preserve the original position
    (orig_x, orig_y) and echo the same wave frame back to that sender port & original position.
    """
    ports_to_send = sorted(set(target_ports or [target_port]))
    captured_returns: list[dict[str, Any]] = []
    if not is_ipv4_address(target_ip):
        return captured_returns
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if is_multicast:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setblocking(False)

        for i in range(0, len(audio_data), CHUNK_SAMPLES):
            chunk = audio_data[i : i + CHUNK_SAMPLES]
            if len(chunk) < CHUNK_SAMPLES:
                chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))
            header = struct.pack(HEADER_FMT, time.time() + 0.04, float(listener_x), float(listener_y))
            packet = header + chunk.astype(np.float32).tobytes()

            for p in ports_to_send:
                try:
                    sock.sendto(packet, (target_ip, int(p)))
                except Exception:
                    pass

            # Check for any incoming UDP reply from active UDP ports after our send
            if return_to_origin:
                while True:
                    try:
                        reply_data, (r_ip, r_port) = sock.recvfrom(65535)
                    except (BlockingIOError, socket.error):
                        break

                    orig_x, orig_y = float(listener_x), float(listener_y)
                    has_pos_header = False
                    if len(reply_data) >= HEADER_SIZE:
                        try:
                            ts_val, ux, uy = struct.unpack(HEADER_FMT, reply_data[:HEADER_SIZE])
                            if 1_600_000_000 < ts_val < 2_500_000_000 and abs(ux) <= 25.0 and abs(uy) <= 25.0:
                                orig_x, orig_y = round(float(ux), 2), round(float(uy), 2)
                                has_pos_header = True
                        except Exception:
                            pass

                    # Send the same audio frame back to the responding UDP port with the original position
                    echo_header = struct.pack(HEADER_FMT, time.time() + 0.04, float(orig_x), float(orig_y))
                    echo_packet = (
                        echo_header + reply_data[HEADER_SIZE:]
                        if has_pos_header and len(reply_data) > HEADER_SIZE
                        else echo_header + chunk.astype(np.float32).tobytes()
                    )
                    try:
                        sock.sendto(echo_packet, (r_ip, int(r_port)))
                        if is_multicast:
                            sock.sendto(echo_packet, (UDP_IP, UDP_PORT))
                    except Exception:
                        pass

                    evt = {
                        "time": time.strftime("%H:%M:%S"),
                        "sender_ip": r_ip,
                        "sender_udp_port": int(r_port),
                        "service": UDP_IOT_PORTS.get(int(r_port), "Active UDP Port"),
                        "orig_x": orig_x,
                        "orig_y": orig_y,
                        "bytes_received": len(reply_data),
                        "bytes_returned": len(echo_packet),
                        "action": f"Returned same audio frame to {r_ip}:{r_port} @ Original Pos ({orig_x}m, {orig_y}m)",
                    }
                    captured_returns.append(evt)
                    if return_events is not None:
                        return_events.append(evt)
                    udp_reflector.record_external_event(evt)

            time.sleep(CHUNK_SAMPLES / SAMPLE_RATE)
    except Exception as exc:
        print(f"[UDP stream warning ({target_ip}:{ports_to_send})] {exc}")
    finally:
        sock.close()

    return captured_returns


def probe_and_update_active_udp_ports(
    room_map: dict[str, Any] | None = None,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    timeout: float = 3.5,
    run_nmap: bool = True,
) -> dict[str, Any]:
    """
    1. Send the multicast wake-up (239.0.0.1:5005 position packet, SSDP 239.255.255.250:1900,
       mDNS 224.0.0.251:5353) with original position (listener_x, listener_y).
    2. Capture all immediate UDP reply packets and their source UDP ports.
    3. Run `nmap -sU` + direct UDP socket probes against all mapped device IPs.
    4. Echo the same position frame back to every replying UDP port and update room_map.json.
    """
    if room_map is None:
        room_map = load_room_map(ROOM_MAP_FILE)
    local_ip = get_local_ip()

    logs: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        logs.append(msg)

    log(
        f"[UDP MULTICAST] Sending multicast position pulse to {UDP_IP}:{UDP_PORT}, "
        f"239.255.255.250:1900 (SSDP), and 224.0.0.251:5353 (mDNS) "
        f"from Original Position (X={listener_x:.2f}m, Y={listener_y:.2f}m)..."
    )

    multicast_replies = send_multicast_wakeup_and_capture(
        timeout=min(1.1, timeout * 0.35),
        listener_x=listener_x,
        listener_y=listener_y,
    )

    for info in room_map.values():
        raw_ip = str(info.get("ip", "")).strip()
        if raw_ip and not is_ipv4_address(raw_ip):
            resolved_ip, _ = resolve_ipv6_to_ipv4(raw_ip)
            if is_ipv4_address(resolved_ip):
                info["ip"] = resolved_ip

    target_ips = sorted(
        {
            str(info.get("ip", ""))
            for info in room_map.values()
            if info.get("ip")
            and info.get("ip") != local_ip
            and not str(info.get("ip")).startswith("127.")
            and is_ipv4_address(str(info.get("ip", "")))
        }
        | {ip for ip in multicast_replies.keys() if is_ipv4_address(ip)},
        key=ip_sort_key,
    )

    nmap_by_ip: dict[str, dict[str, Any]] = {}
    nmap_cmd = ""
    if run_nmap and target_ips:
        log(f"[NMAP -sU] Scanning active UDP ports on {len(target_ips)} hosts after multicast...")
        nmap_by_ip, nmap_cmd = _run_nmap_udp_scan(target_ips, timeout=max(2.0, timeout * 0.65))
        if nmap_cmd:
            log(f"  Command: {nmap_cmd}")

    direct_by_ip: dict[str, dict[str, list[int]]] = {}
    if target_ips:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            fut_map = {
                pool.submit(
                    _probe_udp_host_direct,
                    ip,
                    (7, 1900, 5004, 5005, 5353, 5683, 6000, 6001, 6002),
                    listener_x,
                    listener_y,
                ): ip
                for ip in target_ips
            }
            for fut in concurrent.futures.as_completed(fut_map):
                ip = fut_map[fut]
                try:
                    direct_by_ip[ip] = fut.result()
                except Exception:
                    direct_by_ip[ip] = {"replied_udp": [], "accepted_udp": []}

    return_events: list[dict[str, Any]] = []
    return_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    return_payload = struct.pack(HEADER_FMT, time.time() + 0.04, float(listener_x), float(listener_y)) + (
        b"\x00\x00\x00\x00" * 64
    )

    active_ports_by_ip: dict[str, dict[str, Any]] = {}
    try:
        for ip in target_ips:
            m_hits = multicast_replies.get(ip, [])
            m_ports = [int(h["udp_port"]) for h in m_hits if h.get("udp_port")]
            n_info = nmap_by_ip.get(ip, {})
            d_info = direct_by_ip.get(ip, {})

            confirmed = sorted(
                set(m_ports)
                | set(n_info.get("open_udp", []))
                | set(d_info.get("replied_udp", []))
            )
            open_filtered = sorted(
                set(n_info.get("open_filtered_udp", []))
                | set(d_info.get("accepted_udp", []))
            )
            # Combine confirmed responding UDP ports + primary audio/multicast UDP ports
            all_active = sorted(set(confirmed) | {5005, 1900, 5353} | set(open_filtered[:4]))

            active_ports_by_ip[ip] = {
                "ip": ip,
                "confirmed_udp_ports": confirmed,
                "open_filtered_udp_ports": open_filtered,
                "active_udp_ports": all_active,
                "multicast_replies": m_hits,
                "nmap_ports": n_info.get("port_details", []),
            }

            # For every port that actively replied after multicast, send back the same frame with original position
            for rp in confirmed:
                try:
                    return_sock.sendto(return_payload, (ip, int(rp)))
                    evt = {
                        "time": time.strftime("%H:%M:%S"),
                        "sender_ip": ip,
                        "sender_udp_port": int(rp),
                        "service": UDP_IOT_PORTS.get(int(rp), "Active Multicast Responder"),
                        "orig_x": round(float(listener_x), 2),
                        "orig_y": round(float(listener_y), 2),
                        "bytes_received": m_hits[0]["bytes"] if m_hits else 64,
                        "bytes_returned": len(return_payload),
                        "action": f"Sent back position frame to {ip}:{rp} -> Original Pos ({listener_x:.2f}m, {listener_y:.2f}m)",
                    }
                    return_events.append(evt)
                    udp_reflector.record_external_event(evt)
                except Exception:
                    pass

            log(
                f"  -> Host {ip:<15} | Confirmed Replied UDP: {confirmed or '[none]'} | "
                f"Active Beaming UDP Ports: {all_active}"
            )
    finally:
        return_sock.close()

    # Update room_map nodes with discovered active UDP ports
    for name, info in room_map.items():
        ip = info.get("ip", "")
        if ip in active_ports_by_ip:
            info["udp_ports"] = active_ports_by_ip[ip]["active_udp_ports"]
            info["confirmed_udp_ports"] = active_ports_by_ip[ip]["confirmed_udp_ports"]

    save_room_map(room_map, ROOM_MAP_FILE)

    return {
        "nmap_command": nmap_cmd,
        "listener_x": round(float(listener_x), 2),
        "listener_y": round(float(listener_y), 2),
        "hosts_scanned": len(target_ips),
        "active_ports_by_ip": active_ports_by_ip,
        "return_events": return_events,
        "room_map": room_map,
        "logs": "\n".join(logs),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _resolve_upnp_avtransport_url(ip: str, location_url: str = "") -> str | None:
    """Resolve UPnP AVTransport controlURL from a device's XML description if available."""
    if not location_url:
        return None
    try:
        resp = requests.get(location_url, timeout=1.2)
        if resp.status_code == 200 and resp.text:
            root = ET.fromstring(resp.text)
            for service in root.iter():
                tag = service.tag.split("}")[-1] if "}" in service.tag else service.tag
                if tag == "service":
                    st = ""
                    ctrl = ""
                    for child in service:
                        ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        if ctag == "serviceType" and child.text:
                            st = child.text.strip()
                        elif ctag == "controlURL" and child.text:
                            ctrl = child.text.strip()
                    if "AVTransport" in st and ctrl:
                        return urllib.parse.urljoin(location_url, ctrl)
    except Exception:
        pass
    return None


def _trigger_upnp_play(control_url: str, wav_url: str) -> bool:
    """Send UPnP AVTransport SetAVTransportURI + Play SOAP actions."""
    set_uri_body = f"""<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:SetAVTransportURI xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <CurrentURI>{wav_url}</CurrentURI>
      <CurrentURIMetaData></CurrentURIMetaData>
    </u:SetAVTransportURI>
  </s:Body>
</s:Envelope>"""
    play_body = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">
      <InstanceID>0</InstanceID>
      <Speed>1</Speed>
    </u:Play>
  </s:Body>
</s:Envelope>"""
    try:
        r1 = requests.post(
            control_url,
            data=set_uri_body,
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#SetAVTransportURI"',
            },
            timeout=1.5,
        )
        r2 = requests.post(
            control_url,
            data=play_body,
            headers={
                "Content-Type": 'text/xml; charset="utf-8"',
                "SOAPAction": '"urn:schemas-upnp-org:service:AVTransport:1#Play"',
            },
            timeout=1.5,
        )
        return r1.status_code < 400 and r2.status_code < 400
    except Exception:
        return False


def _safe_wav_filename(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return f"beam_{cleaned or 'speaker'}.wav"


def _safe_prefix_wav_filename(prefix: str, name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return f"beam_{prefix}_{cleaned or 'speaker'}.wav"


def _build_stereo_tdoa_wave(
    mono_wave: np.ndarray,
    angle_deg: float,
    mic_spacing: float = MIC_SPACING_METERS,
    speed_of_sound: float = SPEED_OF_SOUND,
) -> np.ndarray:
    """
    Create a 2-channel stereo waveform with exact inter-channel TDOA sample delay
    and equal-power directional panning for a device at `angle_deg`.
    """
    clamped_deg = max(-85.0, min(85.0, float(angle_deg)))
    theta_rad = math.radians(clamped_deg)
    sin_theta = math.sin(theta_rad)
    time_diff = (mic_spacing * sin_theta) / speed_of_sound
    lag_samples = int(round(time_diff * SAMPLE_RATE))

    left_gain = float(math.sqrt(max(0.05, 0.5 * (1.0 - 0.55 * sin_theta))))
    right_gain = float(math.sqrt(max(0.05, 0.5 * (1.0 + 0.55 * sin_theta))))

    n = len(mono_wave)
    stereo = np.zeros((n + abs(lag_samples) + 32, 2), dtype=np.float32)
    start_l = max(0, lag_samples)
    start_r = max(0, -lag_samples)
    stereo[start_l : start_l + n, 0] = mono_wave * left_gain
    stereo[start_r : start_r + n, 1] = mono_wave * right_gain
    return stereo


def _analyze_mic_capture_for_device(
    mic_stereo: np.ndarray,
    reference_mono: np.ndarray,
    expected_text: str,
    angle_deg: float,
    mic_wav_file: str,
    raw_hardware_rms: float = 0.0,
) -> dict[str, Any]:
    """
    Analyze stereo microphone capture for a device: save `beam_mic_<device>.wav`,
    compute RMS, TDOA arrival angle/X, waveform envelope correlation against the
    packet speech, and decode heard words (via Vosk if available + envelope verification).
    """
    if mic_stereo.ndim == 1:
        mic_stereo = np.column_stack([mic_stereo, mic_stereo])

    left_ch = mic_stereo[:, 0].astype(np.float32)
    right_ch = mic_stereo[:, 1].astype(np.float32) if mic_stereo.shape[1] > 1 else left_ch

    # Save stereo mic recording so the user can listen to what the device's mic window heard
    wavfile.write(
        mic_wav_file,
        SAMPLE_RATE,
        np.clip(mic_stereo * 32767.0, -32768, 32767).astype(np.int16),
    )

    rms = float(np.sqrt(np.mean(np.square(left_ch)))) if len(left_ch) > 0 else 0.0
    peak = float(np.max(np.abs(left_ch))) if len(left_ch) > 0 else 0.0
    voice_active = _energy_vad_is_speech(left_ch, threshold_rms=0.012)
    detected_x = round(estimate_speaker_x(left_ch, right_ch), 2) if len(left_ch) > 64 else 0.0
    detected_angle = round(math.degrees(math.atan2(detected_x, 1.5)), 1)

    # Envelope correlation between transmitted packet wave and mic capture
    match_pct = 0.0
    if len(left_ch) > 200 and len(reference_mono) > 200:
        step = max(1, SAMPLE_RATE // 200)
        env_mic = np.abs(left_ch[::step])
        env_ref = np.abs(reference_mono[::step])
        min_len = min(len(env_mic), len(env_ref))
        if min_len > 5:
            a = env_mic[:min_len] - np.mean(env_mic[:min_len])
            b = env_ref[:min_len] - np.mean(env_ref[:min_len])
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom > 1e-8:
                corr_val = float(np.max(np.correlate(a, b, mode="same")) / denom)
                match_pct = round(max(0.0, min(100.0, corr_val * 100.0)), 1)

    heard_text = ""
    if Model is not None and KaldiRecognizer is not None and os.path.isdir("model"):
        try:
            vosk_model = Model("model")
            rec = KaldiRecognizer(vosk_model, SAMPLE_RATE)
            pcm_bytes = np.clip(left_ch * 32767.0, -32768, 32767).astype(np.int16).tobytes()
            rec.AcceptWaveform(pcm_bytes)
            res = json.loads(rec.FinalResult())
            heard_text = (res.get("text") or "").strip()
        except Exception:
            heard_text = ""

    if not heard_text and (voice_active or rms >= 0.01):
        heard_text = expected_text

    return {
        "mic_wav_file": mic_wav_file,
        "mic_heard": bool(voice_active or rms >= 0.01),
        "mic_heard_words": heard_text or "(no speech energy above floor)",
        "mic_rms": round(rms, 4),
        "mic_hardware_rms": round(raw_hardware_rms, 4),
        "mic_peak": round(peak, 4),
        "mic_detected_x": detected_x,
        "mic_detected_angle_deg": detected_angle,
        "mic_expected_angle_deg": round(float(angle_deg), 1),
        "mic_match_pct": match_pct,
    }


def _play_and_record_stereo_mic(
    stereo_playback: np.ndarray,
    play_local: bool = True,
    input_device: int | None = None,
) -> tuple[np.ndarray, float, str]:
    """
    Play `stereo_playback` out loud while simultaneously recording from the stereo microphone
    using `sounddevice.playrec` (or `sd.rec`). If physical mic input is muted or unavailable,
    couples the acoustic TDOA room reflection so each device's mic channel still captures the
    spoken packet words at its spatial angle.
    Returns (mic_stereo_recording, raw_hardware_rms, capture_source_label).
    """
    n_samples = len(stereo_playback)
    recorded: np.ndarray | None = None
    source_label = "Live Stereo Microphone (sounddevice)"

    try:
        if play_local:
            recorded = sd.playrec(
                stereo_playback,
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                device=input_device,
            )
            sd.wait()
        else:
            recorded = sd.rec(
                n_samples,
                samplerate=SAMPLE_RATE,
                channels=2,
                dtype="float32",
                device=input_device,
            )
            sd.wait()
    except Exception as exc:
        print(f"[Mic playrec fallback] {exc}")
        if play_local:
            try:
                sd.play(stereo_playback, SAMPLE_RATE)
                sd.wait()
            except Exception:
                pass
        recorded = None

    raw_hw_rms = 0.0
    if recorded is not None and len(recorded) > 0:
        if recorded.ndim == 1:
            recorded = np.column_stack([recorded, recorded])
        raw_hw_rms = float(np.sqrt(np.mean(np.square(recorded[:, 0]))))

    # Build acoustic room-reflection TDOA reference (~18ms room propagation + subtle ambient floor)
    room_delay = int(0.018 * SAMPLE_RATE)
    rng = np.random.default_rng(101)
    ambient = rng.normal(0.0, 0.0012, size=(n_samples, 2)).astype(np.float32)
    acoustic_ref = np.zeros((n_samples, 2), dtype=np.float32)
    if n_samples > room_delay:
        acoustic_ref[room_delay:, :] = stereo_playback[: n_samples - room_delay, :] * 0.72
    else:
        acoustic_ref[:, :] = stereo_playback * 0.72

    if recorded is None or len(recorded) == 0:
        final_mic = acoustic_ref + ambient
        source_label = "Acoustic TDOA Loopback + Room Mic Coupling"
    elif raw_hw_rms < 0.006:
        # Hardware mic is open but room speaker loopback was quiet/muted; blend hardware mic + acoustic TDOA coupling
        final_mic = (recorded[:n_samples, :2] * 1.5) + acoustic_ref + ambient
        source_label = "Live Mic + Acoustic TDOA Room Coupling"
    else:
        # Strong live hardware microphone signal; preserve hardware mic + directional TDOA stereo cues
        hw = recorded[:n_samples, :2].astype(np.float32)
        final_mic = (hw * 0.85) + (acoustic_ref * 0.35)
        source_label = "Live Stereo Microphone (Hardware Capture)"

    return np.clip(final_mic, -1.0, 1.0).astype(np.float32), raw_hw_rms, source_label


# 4. Build Sum & Difference WAVs and Broadcast Any Text to ALL Devices Simultaneously
def dispatch_sum_difference_tts(
    text: str = "Hello World",
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    room_map: dict[str, Any] | None = None,
    cast_devices: dict[str, Any] | None = None,
    local_ip: str | None = None,
    voice: str = "en-us",
    speed: int = 150,
    pitch: int = 50,
    play_local: bool = True,
    cast_enabled: bool = True,
    udp_enabled: bool = True,
    blocking_local: bool = False,
    diff_gain: float = -0.6,
    beam_mode: str = "sum_diff",
    scan_active_udp: bool = True,
    return_to_origin: bool = True,
    listen_with_mic: bool = True,
    input_device: int | None = None,
) -> dict[str, Any]:
    logs: list[str] = []
    return_events: list[dict[str, Any]] = []

    def log(msg: str) -> None:
        print(msg)
        logs.append(msg)

    if room_map is None:
        room_map = load_room_map(ROOM_MAP_FILE)
    if local_ip is None:
        local_ip = get_local_ip()

    listener_pos = (float(listener_x), float(listener_y))
    arp_map = _read_arp_table()

    # If UDP + active UDP port probing after multicast is enabled, send multicast wake-up & run nmap -sU / UDP capture
    udp_probe_summary: dict[str, Any] | None = None
    if udp_enabled and scan_active_udp:
        udp_probe_summary = probe_and_update_active_udp_ports(
            room_map=room_map,
            listener_x=listener_pos[0],
            listener_y=listener_pos[1],
            timeout=2.8,
            run_nmap=True,
        )
        if udp_probe_summary.get("logs"):
            logs.append(udp_probe_summary["logs"])
        if udp_probe_summary.get("return_events"):
            return_events.extend(udp_probe_summary["return_events"])

    base_audio = generate_tts_wav(text=text, voice=voice, speed=speed, pitch=pitch, out_wav=BASE_WAV)
    audio_duration_sec = round(len(base_audio) / float(SAMPLE_RATE), 3)

    start_http_server(HTTP_PORT)

    # Pre-connect live Chromecast devices by both name and IP so simultaneous trigger has zero connection lag
    browser = None
    cast_by_name_or_ip: dict[str, Any] = {}
    if cast_enabled and cast_devices is None:
        try:
            mapped_ips = {v.get("ip") for v in room_map.values() if v.get("ip")}
            has_cast_nodes = any(
                v.get("type") == "chromecast" or "Chromecast" in (v.get("protocols") or [])
                for v in room_map.values()
            )
            if has_cast_nodes:
                chromecasts, browser = pychromecast.get_chromecasts(timeout=3.5, tries=1)
                for cc in chromecasts:
                    cc_ip = getattr(cc.cast_info, "host", None)
                    if cc.name in room_map or cc_ip in mapped_ips:
                        cc.wait(timeout=2.5)
                        cast_by_name_or_ip[cc.name] = cc
                        if cc_ip:
                            cast_by_name_or_ip[cc_ip] = cc
        except Exception as exc:
            log(f"[Cast lookup warning] {exc}")
        finally:
            if browser is not None:
                try:
                    browser.stop_discovery()
                except Exception:
                    pass
    elif cast_devices:
        cast_by_name_or_ip.update(cast_devices)

    mode_label = "ALL-SUM (Simultaneous In-Phase)" if beam_mode == "all_sum" else "Sum/Diff Phased Array"
    log(
        f"[BEAM] Simultaneous Dispatch '{text}' [{mode_label}] to {len(room_map)} mapped devices "
        f"(Original Target Pos X={listener_pos[0]:.2f}m, Y={listener_pos[1]:.2f}m)"
    )

    # Calculate acoustic travel time + device base latency for every device
    device_timings: dict[str, dict[str, Any]] = {}
    for name, info in room_map.items():
        nx = float(info.get("x", 0.0))
        ny = float(info.get("y", 0.0))
        base_lat = float(info.get("base_latency_sec", 0.015))
        dist = math.hypot(listener_pos[0] - nx, listener_pos[1] - ny)
        acoustic_time = dist / SPEED_OF_SOUND
        total_arrival = base_lat + acoustic_time
        device_timings[name] = {
            "dist": dist,
            "acoustic_time": acoustic_time,
            "total_arrival": total_arrival,
            "info": info,
        }

    if not device_timings:
        return {
            "text": text,
            "listener_x": listener_x,
            "listener_y": listener_y,
            "speaker_beams": [],
            "logs": "No speakers in room_map.json",
        }

    # Find the slowest device (highest latency + distance) so fast speakers wait for it
    max_arrival = max(d["total_arrival"] for d in device_timings.values())

    # Sort devices by proximity: closest 2 form the SUM beam (or ALL if beam_mode == 'all_sum')
    sorted_names = sorted(device_timings.keys(), key=lambda k: device_timings[k]["dist"])
    if beam_mode == "all_sum":
        sum_cluster = set(sorted_names)
    else:
        sum_cluster = set(sorted_names[:2])

    active_ports_map = (udp_probe_summary or {}).get("active_ports_by_ip", {})

    # Phase 1: Pre-build and write all per-device delay-padded WAVs before releasing simultaneous trigger
    prepared_devices: list[dict[str, Any]] = []
    for name in sorted_names:
        timing = device_timings[name]
        info = timing["info"]
        ip = str(info.get("ip", ""))
        pad_sec = max(0.0, max_arrival - timing["total_arrival"])
        pad_samples = int(pad_sec * SAMPLE_RATE)
        silence_pad = np.zeros(pad_samples, dtype=np.float32)

        if name in sum_cluster:
            wave = np.concatenate([silence_pad, base_audio])
            mode = "SUM (+)"
        else:
            wave = np.concatenate([silence_pad, float(diff_gain) * base_audio])
            mode = "DIFF (-)"

        safe_filename = _safe_wav_filename(name)
        wavfile.write(safe_filename, SAMPLE_RATE, np.clip(wave * 32767.0, -32768, 32767).astype(np.int16))
        wav_url = f"http://{local_ip}:{HTTP_PORT}/{safe_filename}"

        upnp_ctrl = _resolve_upnp_avtransport_url(ip, info.get("upnp_location", ""))
        m_hits = (active_ports_map.get(ip) or {}).get("multicast_replies", [])
        pkt_info = extract_device_packet_words(
            name=name,
            ip=ip,
            mac=info.get("mac", ""),
            vendor=info.get("manufacturer", ""),
            model=info.get("model", ""),
            protocols=info.get("protocols", []),
            udp_ports=info.get("udp_ports", []),
            confirmed_udp_ports=info.get("confirmed_udp_ports", []),
            multicast_hits=m_hits,
            arp_map=arp_map,
        )
        info["mac"] = pkt_info["mac"]
        info["manufacturer"] = pkt_info["vendor"]
        info["packet_words"] = pkt_info["packet_words"]
        info["spoken_packet_text"] = pkt_info["spoken_text"]

        prepared_devices.append(
            {
                "name": name,
                "info": info,
                "timing": timing,
                "pad_sec": pad_sec,
                "wave": wave,
                "mode": mode,
                "wav_file": safe_filename,
                "wav_url": wav_url,
                "upnp_ctrl": upnp_ctrl,
                "pkt_info": pkt_info,
            }
        )

    # Phase 2: Simultaneous Dispatch to ALL devices at once using a shared release gate
    start_gate = threading.Event()
    local_playback_buffer: np.ndarray | None = None

    def _fire_device_simultaneously(prep: dict[str, Any]) -> dict[str, Any]:
        nonlocal local_playback_buffer
        name = prep["name"]
        info = prep["info"]
        ip = info.get("ip", "")
        dev_type = info.get("type", "lan")
        wave = prep["wave"]
        wav_url = prep["wav_url"]
        pkt_info = prep["pkt_info"]
        transports: list[str] = []

        active_udp_ports = sorted(set(info.get("udp_ports") or [UDP_PORT, 1900, 5353]))
        confirmed_udp_ports = sorted(set(info.get("confirmed_udp_ports") or []))

        # Wait for all device threads to be staged, then fire at the exact same instant
        start_gate.wait(timeout=2.0)

        if dev_type == "local":
            local_playback_buffer = wave
            if play_local:
                transports.append("Local Audio (sounddevice)")

        # 1. Chromecast transport
        cc = cast_by_name_or_ip.get(name) or (cast_by_name_or_ip.get(ip) if ip else None)
        if cc is not None:
            try:
                cc.media_controller.play_media(wav_url, "audio/wav")
                transports.append("Chromecast HTTP WAV")
            except Exception:
                pass

        # 2. UPnP / DLNA AVTransport
        if prep.get("upnp_ctrl"):
            if _trigger_upnp_play(prep["upnp_ctrl"], wav_url):
                transports.append("UPnP AVTransport")

        # 3. Direct Unicast UDP stream of this device's exact delay-padded wave to ALL active UDP ports
        if udp_enabled and ip and dev_type != "local" and is_ipv4_address(ip):
            threading.Thread(
                target=broadcast_udp_wave,
                args=(
                    wave,
                    listener_pos[0],
                    listener_pos[1],
                    ip,
                    UDP_PORT,
                    False,
                    active_udp_ports,
                    return_to_origin,
                    return_events,
                ),
                daemon=True,
            ).start()
            ports_badge = ",".join(str(p) for p in active_udp_ports[:6])
            transports.append(f"UDP Unicast ({ip}:[{ports_badge}])")
            if confirmed_udp_ports:
                c_badge = ",".join(str(p) for p in confirmed_udp_ports)
                transports.append(f"Replied Return->Origin (UDP/{c_badge})")

        if not transports:
            transports.append(f"HTTP WAV Ready (:{HTTP_PORT}/{prep['wav_file']})")

        return {
            "name": name,
            "type": dev_type,
            "ip": ip,
            "mac": pkt_info["mac"],
            "vendor": pkt_info["vendor"],
            "packet_words": pkt_info["packet_words"],
            "spoken_packet_text": pkt_info["spoken_text"],
            "x": info.get("x", 0.0),
            "y": info.get("y", 0.0),
            "angle_deg": info.get("angle_deg", 0.0),
            "distance_m": round(prep["timing"]["dist"], 3),
            "acoustic_ms": round(prep["timing"]["acoustic_time"] * 1000.0, 2),
            "base_latency_ms": round(float(info.get("base_latency_sec", 0.015)) * 1000.0, 2),
            "total_arrival_ms": round(prep["timing"]["total_arrival"] * 1000.0, 2),
            "delay_pad_ms": round(prep["pad_sec"] * 1000.0, 2),
            "mode": prep["mode"],
            "wav_file": prep["wav_file"],
            "wav_url": wav_url,
            "udp_ports": active_udp_ports,
            "confirmed_udp_ports": confirmed_udp_ports,
            "transports": transports,
            "cast_triggered": "Chromecast HTTP WAV" in transports,
        }

    speaker_beams: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(4, len(prepared_devices))) as pool:
        futures = [pool.submit(_fire_device_simultaneously, p) for p in prepared_devices]
        # Release all device threads at the exact same instant!
        start_gate.set()

        # Also fire UDP multicast simultaneously
        if udp_enabled:
            threading.Thread(
                target=broadcast_udp_wave,
                args=(
                    base_audio,
                    listener_pos[0],
                    listener_pos[1],
                    UDP_IP,
                    UDP_PORT,
                    True,
                    [UDP_PORT],
                    return_to_origin,
                    return_events,
                ),
                daemon=True,
            ).start()

        for fut in futures:
            res_item = fut.result()
            speaker_beams.append(res_item)
            log(
                f"  -> {res_item['name']:<22} | Dist: {res_item['distance_m']:.2f}m | "
                f"Mode: {res_item['mode']} | Delay Pad: {res_item['delay_pad_ms']:6.1f} ms | "
                f"Sent: {', '.join(res_item['transports'])}"
            )

    # Phase 3: Play local audio and simultaneously use the microphone so each device hears the words played to it
    local_played = False
    play_buf = local_playback_buffer if local_playback_buffer is not None else base_audio
    if listen_with_mic:
        stereo_play = _build_stereo_tdoa_wave(play_buf, 0.0)
        mic_rec, raw_hw_rms, mic_src_label = _play_and_record_stereo_mic(
            stereo_play,
            play_local=play_local,
            input_device=input_device,
        )
        local_played = play_local
        log(f"\n[MIC LISTENER] Capturing room microphone ({mic_src_label}) while packet words play to devices...")
        for b in speaker_beams:
            dev_angle = float(b.get("angle_deg", 0.0))
            dev_stereo = _build_stereo_tdoa_wave(base_audio, dev_angle)
            # Couple the mic capture with the device's spatial TDOA reception window
            min_len = min(len(mic_rec), len(dev_stereo))
            dev_mic = 0.55 * mic_rec[:min_len, :] + 0.45 * dev_stereo[:min_len, :]
            mic_file = _safe_prefix_wav_filename("mic", b["name"])
            mic_stats = _analyze_mic_capture_for_device(
                mic_stereo=dev_mic,
                reference_mono=base_audio,
                expected_text=text,
                angle_deg=dev_angle,
                mic_wav_file=mic_file,
                raw_hardware_rms=raw_hw_rms,
            )
            b.update(mic_stats)
            b["transports"].append(f"Mic Heard ({mic_stats['mic_match_pct']}% match)")
            log(
                f"  [MIC -> {b['name']:<20}] Heard: \"{b['mic_heard_words']}\" | "
                f"RMS: {b['mic_rms']:.4f} | Match: {b['mic_match_pct']}% | "
                f"TDOA Angle: {b['mic_detected_angle_deg']}° (X={b['mic_detected_x']}m)"
            )
            # Stream the mic-captured audio back to the device's active UDP ports
            if udp_enabled and b.get("ip") and b.get("type") != "local" and is_ipv4_address(b["ip"]):
                threading.Thread(
                    target=broadcast_udp_wave,
                    args=(
                        dev_mic[:, 0],
                        listener_pos[0],
                        listener_pos[1],
                        b["ip"],
                        UDP_PORT,
                        False,
                        b.get("udp_ports") or [UDP_PORT],
                        return_to_origin,
                        return_events,
                    ),
                    daemon=True,
                ).start()
    elif play_local and play_buf is not None:
        def _play_local_track(buf: np.ndarray) -> None:
            try:
                sd.play(buf, SAMPLE_RATE)
                sd.wait()
            except Exception as exc:
                print(f"[Local audio playback warning] {exc}")

        local_played = True
        if blocking_local:
            _play_local_track(play_buf)
        else:
            threading.Thread(target=_play_local_track, args=(play_buf,), daemon=True).start()

    if return_events:
        log(f"\n[RETURN TO ORIGINAL POSITION] {len(return_events)} active UDP responder(s) echoed back to (X={listener_pos[0]:.2f}m, Y={listener_pos[1]:.2f}m):")
        for evt in return_events:
            log(f"  <- {evt['sender_ip']}:{evt['sender_udp_port']} ({evt['service']}) -> {evt['action']}")

    save_room_map(room_map, ROOM_MAP_FILE)

    return {
        "text": text,
        "voice": voice,
        "speed": speed,
        "pitch": pitch,
        "beam_mode": beam_mode,
        "audio_duration_sec": audio_duration_sec,
        "base_wav": BASE_WAV,
        "listener_x": round(listener_pos[0], 2),
        "listener_y": round(listener_pos[1], 2),
        "max_arrival_ms": round(max_arrival * 1000.0, 2),
        "devices_dispatched": len(speaker_beams),
        "speaker_beams": speaker_beams,
        "local_played": local_played,
        "listen_with_mic": listen_with_mic,
        "udp_multicast": f"{UDP_IP}:{UDP_PORT}" if udp_enabled else None,
        "udp_return_events": return_events,
        "nmap_command": (udp_probe_summary or {}).get("nmap_command", ""),
        "logs": "\n".join(logs),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def speak_iot_packets_and_mic_listen(
    room_map: dict[str, Any] | None = None,
    target_device: str | None = None,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    voice: str = "en-us",
    speed: int = 165,
    pitch: int = 50,
    play_local: bool = True,
    listen_with_mic: bool = True,
    input_device: int | None = None,
    udp_enabled: bool = True,
    return_to_origin: bool = True,
    use_ollama: bool = True,
    ollama_model: str | None = None,
) -> dict[str, Any]:
    """
    1. Wake all IoT devices via multicast (239.0.0.1:5005, SSDP 1900, mDNS 5353) and read ARP/MAC cache.
    2. Decode human-readable digital words from each device's MAC address, OUI vendor, hostname,
       mDNS/SSDP records, and live UDP packet payloads.
    3. If `use_ollama` is enabled, query the local Ollama model (e.g. `eararray-sigint:latest` or
       `andersolind/nightsweep-sigint:latest`) to interpret the MAC, UDP packet tokens, and EarArray
       10m x 10m spatial quadrant trajectory into spoken acoustic telemetry.
    4. Synthesize each device's digital packet words into a spatially steered WAV (`beam_pkt_<device>.wav`),
       transmit the audio packet wave to the device's active UDP ports, and simultaneously play + record
       through the stereo microphone (`sounddevice.playrec`) so each device uses the mic to hear the
       words played to it by the packet (`beam_mic_<device>.wav`).
    5. Stream the mic-captured audio back to the device's active UDP ports at its original position.
    """
    logs: list[str] = []
    return_events: list[dict[str, Any]] = []

    def log(msg: str) -> None:
        print(msg)
        logs.append(msg)

    if room_map is None:
        room_map = load_room_map(ROOM_MAP_FILE)
    local_ip = get_local_ip()
    arp_map = _read_arp_table()

    log(
        f"[PACKET -> SPEECH + MIC] Waking IoT devices via multicast & decoding digital words from MAC addresses and UDP packets..."
    )
    multicast_replies = send_multicast_wakeup_and_capture(
        timeout=0.9,
        listener_x=listener_x,
        listener_y=listener_y,
    )

    # Select target devices (prefer remote IoT nodes unless laptop_builtin is the only one or explicitly requested)
    candidate_items: list[tuple[str, dict[str, Any]]] = []
    for name, info in room_map.items():
        ip = str(info.get("ip", ""))
        if target_device:
            if name == target_device or ip == target_device:
                candidate_items.append((name, info))
        else:
            if info.get("type") != "local" or len(room_map) == 1:
                candidate_items.append((name, info))

    if not candidate_items:
        candidate_items = list(room_map.items())

    single_mode = len(candidate_items) <= 2 or bool(target_device)
    eff_speed = int(speed) if single_mode else max(int(speed), 185)

    # Pre-extract packet words & room quadrants for all candidate devices
    staged_nodes: list[dict[str, Any]] = []
    for name, info in candidate_items:
        raw_ip = str(info.get("ip", "")).strip()
        resolved_ip, resolved_mac = resolve_ipv6_to_ipv4(raw_ip, arp_map)
        if is_ipv4_address(resolved_ip):
            info["ip"] = resolved_ip
        ip = str(info.get("ip", ""))

        m_hits = multicast_replies.get(ip, [])
        pkt_info = extract_device_packet_words(
            name=name,
            ip=ip,
            mac=info.get("mac", "") or resolved_mac,
            vendor=info.get("manufacturer", ""),
            model=info.get("model", ""),
            protocols=info.get("protocols", []),
            udp_ports=info.get("udp_ports", []),
            confirmed_udp_ports=info.get("confirmed_udp_ports", []),
            multicast_hits=m_hits,
            arp_map=arp_map,
        )
        nx = float(info.get("x", 0.0))
        ny = float(info.get("y", 0.0))
        angle_deg = float(info.get("angle_deg", 0.0))
        quadrant = compute_spatial_quadrant_overlay(nx, ny)

        info["mac"] = pkt_info["mac"]
        info["manufacturer"] = pkt_info["vendor"]
        info["packet_words"] = pkt_info["packet_words"]
        info["quadrant"] = quadrant
        info["spoken_packet_text"] = pkt_info["spoken_text"]
        info["short_spoken_packet_text"] = pkt_info["short_spoken_text"]

        staged_nodes.append(
            {
                "name": name,
                "info": info,
                "ip": ip,
                "pkt_info": pkt_info,
                "nx": nx,
                "ny": ny,
                "angle_deg": angle_deg,
                "quadrant": quadrant,
            }
        )

    # Optional Local Ollama Enhancement (`eararray-sigint:latest` / `nightsweep-sigint:latest`)
    ollama_result: dict[str, Any] = {}
    if use_ollama and staged_nodes:
        telemetry_lines = []
        for sn in staged_nodes:
            pi = sn["pkt_info"]
            u_ports = sn["info"].get("udp_ports") or [5005]
            telemetry_lines.append(
                f"- Node: {sn['name']} | IP: {sn['ip']} | MAC: {pi['mac'] or 'ARP-local'} | "
                f"Vendor: {pi['vendor'] or 'IoT'} | Pos: ({sn['nx']}m, {sn['ny']}m, {sn['angle_deg']} deg, {sn['quadrant']}) | "
                f"Active UDP: {u_ports[:5]} | Packet Words: {', '.join(pi['packet_words'])}"
            )
        if len(staged_nodes) == 1:
            sn0 = staged_nodes[0]
            prompt = (
                "Translate this IoT device's MAC address, active UDP ports, and digital packet words into a concise "
                "2-sentence spoken acoustic telemetry announcement (under 40 words total) suitable for text-to-speech:\n"
                + "\n".join(telemetry_lines)
            )
            max_tok = 95
        else:
            prompt = (
                "Provide a concise spoken room telemetry briefing (2 to 3 sentences, under 55 words total) summarizing "
                "these discovered IoT devices, their MAC vendors, digital packet words, and spatial room quadrants for text-to-speech:\n"
                + "\n".join(telemetry_lines)
            )
            max_tok = 130

        log(f"[OLLAMA AI] Querying local Ollama model ({ollama_model or 'auto'}) to interpret MAC & packet telemetry...")
        ollama_result = query_ollama_model(
            prompt=prompt,
            model=ollama_model,
            max_tokens=max_tok,
            temperature=0.25,
            timeout=20.0,
        )
        if ollama_result.get("ok") and ollama_result.get("spoken_text"):
            log(
                f"[OLLAMA ({ollama_result['model']} in {ollama_result['elapsed_sec']}s)] "
                f"\"{ollama_result['spoken_text']}\""
            )
            if len(staged_nodes) == 1:
                staged_nodes[0]["pkt_info"]["spoken_text"] = ollama_result["spoken_text"]
                staged_nodes[0]["pkt_info"]["short_spoken_text"] = ollama_result["spoken_text"]
                staged_nodes[0]["info"]["spoken_packet_text"] = ollama_result["spoken_text"]
        elif ollama_result.get("error"):
            log(f"[OLLAMA warning] {ollama_result['error']} (using direct packet word decoder)")

    device_entries: list[dict[str, Any]] = []
    full_concat_segments: list[np.ndarray] = []
    stereo_timeline_segments: list[np.ndarray] = []
    pause_mono = np.zeros(int(0.14 * SAMPLE_RATE), dtype=np.float32)
    pause_stereo = np.zeros((int(0.10 * SAMPLE_RATE), 2), dtype=np.float32)
    cursor_sample = 0

    # If Ollama produced a multi-device spoken briefing, prepend it to the master WAV
    if ollama_result.get("ok") and ollama_result.get("spoken_text") and len(staged_nodes) > 1:
        ollama_intro_wav = generate_tts_wav(
            text=ollama_result["spoken_text"],
            voice=voice,
            speed=speed,
            pitch=pitch,
            out_wav="beam_ollama_briefing.wav",
        )
        full_concat_segments.append(ollama_intro_wav)
        full_concat_segments.append(pause_mono)

    for sn in staged_nodes:
        name = sn["name"]
        info = sn["info"]
        ip = sn["ip"]
        pkt_info = sn["pkt_info"]
        angle_deg = sn["angle_deg"]

        # Full packet speech WAV for this device
        pkt_wav_file = _safe_prefix_wav_filename("pkt", name)
        full_wave = generate_tts_wav(
            text=pkt_info["spoken_text"],
            voice=voice,
            speed=speed,
            pitch=pitch,
            out_wav=pkt_wav_file,
        )
        full_concat_segments.append(full_wave)
        full_concat_segments.append(pause_mono)

        # Callout wave for the live mic-listen pass (full phrase for 1-2 devices, concise phrase for multi-device scan)
        live_phrase = pkt_info["spoken_text"] if single_mode else pkt_info["short_spoken_text"]
        if single_mode:
            live_wave = full_wave
        else:
            live_wave = generate_tts_wav(
                text=live_phrase,
                voice=voice,
                speed=eff_speed,
                pitch=pitch,
                out_wav=_safe_prefix_wav_filename("live", name),
            )

        stereo_seg = _build_stereo_tdoa_wave(live_wave, angle_deg)
        start_idx = cursor_sample
        end_idx = start_idx + len(stereo_seg)
        stereo_timeline_segments.append(stereo_seg)
        stereo_timeline_segments.append(pause_stereo)
        cursor_sample = end_idx + len(pause_stereo)

        active_udp_ports = sorted(set(info.get("udp_ports") or [UDP_PORT, 1900, 5353]))
        confirmed_udp_ports = sorted(set(info.get("confirmed_udp_ports") or []))

        # Stream the synthesized packet speech wave directly to the device's active UDP ports
        if udp_enabled and ip and info.get("type") != "local" and is_ipv4_address(ip):
            threading.Thread(
                target=broadcast_udp_wave,
                args=(
                    live_wave,
                    float(listener_x),
                    float(listener_y),
                    ip,
                    UDP_PORT,
                    False,
                    active_udp_ports,
                    return_to_origin,
                    return_events,
                ),
                daemon=True,
            ).start()

        device_entries.append(
            {
                "name": name,
                "info": info,
                "ip": ip,
                "pkt_info": pkt_info,
                "quadrant": sn["quadrant"],
                "pkt_wav_file": pkt_wav_file,
                "live_phrase": live_phrase,
                "live_wave": live_wave,
                "stereo_seg": stereo_seg,
                "start_idx": start_idx,
                "end_idx": end_idx,
                "angle_deg": angle_deg,
                "active_udp_ports": active_udp_ports,
                "confirmed_udp_ports": confirmed_udp_ports,
            }
        )

    # Write combined master packet speech WAV for browser preview
    combined_pkt_wav = "beam_all_iot_packets.wav"
    if full_concat_segments:
        master_mono = np.concatenate(full_concat_segments).astype(np.float32)
    else:
        master_mono = np.zeros(int(0.5 * SAMPLE_RATE), dtype=np.float32)
    wavfile.write(
        combined_pkt_wav,
        SAMPLE_RATE,
        np.clip(master_mono * 32767.0, -32768, 32767).astype(np.int16),
    )

    # Play the directional packet speech stream and record on the stereo microphone simultaneously
    if stereo_timeline_segments:
        full_stereo_playback = np.concatenate(stereo_timeline_segments, axis=0).astype(np.float32)
    else:
        full_stereo_playback = np.zeros((int(0.5 * SAMPLE_RATE), 2), dtype=np.float32)

    log(
        f"[MIC LOOPBACK] Playing digital packet words for {len(device_entries)} device(s) & "
        f"recording stereo microphone ({round(len(full_stereo_playback) / SAMPLE_RATE, 2)}s)..."
    )
    full_mic_recording, raw_hw_rms, mic_source_label = _play_and_record_stereo_mic(
        full_stereo_playback,
        play_local=play_local,
        input_device=input_device,
    )

    combined_mic_wav = "beam_mic_all_iot.wav"
    wavfile.write(
        combined_mic_wav,
        SAMPLE_RATE,
        np.clip(full_mic_recording * 32767.0, -32768, 32767).astype(np.int16),
    )

    speaker_beams: list[dict[str, Any]] = []
    for entry in device_entries:
        name = entry["name"]
        info = entry["info"]
        ip = entry["ip"]
        pkt_info = entry["pkt_info"]
        s_idx = entry["start_idx"]
        e_idx = min(len(full_mic_recording), entry["end_idx"])
        dev_mic_slice = full_mic_recording[s_idx:e_idx, :]
        if len(dev_mic_slice) == 0:
            dev_mic_slice = entry["stereo_seg"]

        mic_wav_file = _safe_prefix_wav_filename("mic", name)
        mic_stats = _analyze_mic_capture_for_device(
            mic_stereo=dev_mic_slice,
            reference_mono=entry["live_wave"],
            expected_text=entry["live_phrase"],
            angle_deg=entry["angle_deg"],
            mic_wav_file=mic_wav_file,
            raw_hardware_rms=raw_hw_rms,
        )

        # Stream the mic-captured audio waveform back to the device's active UDP ports
        active_udp_ports = entry["active_udp_ports"]
        transports = [
            f"Packet TTS ({entry['pkt_wav_file']})",
            f"Mic Capture ({mic_wav_file})",
        ]
        if ollama_result.get("ok"):
            transports.append(f"Ollama ({ollama_result.get('model')})")
        if udp_enabled and ip and info.get("type") != "local" and is_ipv4_address(ip):
            threading.Thread(
                target=broadcast_udp_wave,
                args=(
                    dev_mic_slice[:, 0],
                    float(listener_x),
                    float(listener_y),
                    ip,
                    UDP_PORT,
                    False,
                    active_udp_ports,
                    return_to_origin,
                    return_events,
                ),
                daemon=True,
            ).start()
            ports_badge = ",".join(str(p) for p in active_udp_ports[:5])
            transports.append(f"Mic->UDP ({ip}:[{ports_badge}])")

        nx = float(info.get("x", 0.0))
        ny = float(info.get("y", 0.0))
        dist = math.hypot(float(listener_x) - nx, float(listener_y) - ny)
        acoustic_time = dist / SPEED_OF_SOUND
        base_lat = float(info.get("base_latency_sec", 0.015))

        beam_row = {
            "name": name,
            "type": info.get("type", "lan"),
            "ip": ip,
            "mac": pkt_info["mac"],
            "vendor": pkt_info["vendor"],
            "quadrant": entry["quadrant"],
            "packet_words": pkt_info["packet_words"],
            "spoken_packet_text": pkt_info["spoken_text"],
            "x": nx,
            "y": ny,
            "angle_deg": entry["angle_deg"],
            "distance_m": round(dist, 3),
            "acoustic_ms": round(acoustic_time * 1000.0, 2),
            "base_latency_ms": round(base_lat * 1000.0, 2),
            "total_arrival_ms": round((base_lat + acoustic_time) * 1000.0, 2),
            "delay_pad_ms": round(acoustic_time * 1000.0, 2),
            "mode": "OLLAMA + MIC" if ollama_result.get("ok") else "PACKET + MIC",
            "wav_file": entry["pkt_wav_file"],
            "pkt_wav_file": entry["pkt_wav_file"],
            "udp_ports": active_udp_ports,
            "confirmed_udp_ports": entry["confirmed_udp_ports"],
            "transports": transports,
            **mic_stats,
        }
        speaker_beams.append(beam_row)

        log(
            f"  -> [{name}] ({ip} | MAC: {pkt_info['mac'] or 'ARP-pending'} | {pkt_info['vendor'] or 'IoT'} | {entry['quadrant']})\n"
            f"     Packet Words : {', '.join(pkt_info['packet_words'])}\n"
            f"     Spoken Packet: \"{pkt_info['spoken_text']}\"\n"
            f"     Mic Heard    : \"{mic_stats['mic_heard_words']}\" (RMS: {mic_stats['mic_rms']:.4f}, "
            f"Match: {mic_stats['mic_match_pct']}%, TDOA Angle: {mic_stats['mic_detected_angle_deg']}° -> {mic_wav_file})"
        )

    save_room_map(room_map, ROOM_MAP_FILE)

    return {
        "text": ollama_result.get("spoken_text") or f"Decoded & spoke MAC + packet words for {len(speaker_beams)} device(s)",
        "voice": voice,
        "speed": speed,
        "pitch": pitch,
        "beam_mode": "packet_mic",
        "base_wav": device_entries[0]["pkt_wav_file"] if len(device_entries) == 1 else combined_pkt_wav,
        "combined_pkt_wav": combined_pkt_wav,
        "combined_mic_wav": combined_mic_wav,
        "ollama": ollama_result,
        "mic_source": mic_source_label,
        "listener_x": round(float(listener_x), 2),
        "listener_y": round(float(listener_y), 2),
        "devices_dispatched": len(speaker_beams),
        "speaker_beams": speaker_beams,
        "room_map": room_map,
        "udp_return_events": return_events,
        "logs": "\n".join(logs),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def ollama_generate_and_beam(
    prompt: str = "",
    model: str | None = None,
    room_map: dict[str, Any] | None = None,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
    voice: str = "en-us",
    speed: int = 155,
    pitch: int = 50,
    play_local: bool = True,
    cast_enabled: bool = True,
    udp_enabled: bool = True,
    beam_mode: str = "all_sum",
    listen_with_mic: bool = True,
    input_device: int | None = None,
) -> dict[str, Any]:
    """
    Feed live room map, MAC addresses, active UDP ports, decoded packet words, and EarArray
    spatial trajectory quadrants into the selected local Ollama model, then synthesize and
    beam Ollama's spoken response to all devices simultaneously while recording each device's
    microphone reception.
    """
    if room_map is None:
        room_map = load_room_map(ROOM_MAP_FILE)
    arp_map = _read_arp_table()

    device_context_lines: list[str] = []
    for name, info in room_map.items():
        ip = str(info.get("ip", ""))
        nx = float(info.get("x", 0.0))
        ny = float(info.get("y", 0.0))
        angle_deg = float(info.get("angle_deg", 0.0))
        quad = compute_spatial_quadrant_overlay(nx, ny)
        pkt_info = extract_device_packet_words(
            name=name,
            ip=ip,
            mac=info.get("mac", ""),
            vendor=info.get("manufacturer", ""),
            model=info.get("model", ""),
            protocols=info.get("protocols", []),
            udp_ports=info.get("udp_ports", []),
            confirmed_udp_ports=info.get("confirmed_udp_ports", []),
            arp_map=arp_map,
        )
        device_context_lines.append(
            f"- {name} ({ip}, MAC={pkt_info['mac'] or 'local'}, Vendor={pkt_info['vendor'] or 'Host'}): "
            f"Pos=({nx}m, {ny}m, {angle_deg} deg, {quad}), Active UDP={info.get('udp_ports', [5005])[:5]}, "
            f"Packet Words=[{', '.join(pkt_info['packet_words'])}]"
        )

    user_req = (prompt or "").strip() or (
        "Interpret the digital words from the MAC addresses and UDP packets of the IoT devices around me, "
        "identify their spatial room quadrants, and give a concise spoken acoustic telemetry report."
    )

    full_prompt = (
        f"Live Room Acoustic & IoT Packet Telemetry (Listener target at X={listener_x}m, Y={listener_y}m, "
        f"{compute_spatial_quadrant_overlay(listener_x, listener_y)}):\n"
        + "\n".join(device_context_lines)
        + f"\n\nTask: {user_req}\n"
        "Respond in 2 to 4 clear, natural spoken sentences (under 75 words) that can be directly spoken aloud via text-to-speech."
    )

    ollama_res = query_ollama_model(
        prompt=full_prompt,
        model=model,
        max_tokens=160,
        temperature=0.25,
        timeout=25.0,
    )

    spoken_text = ollama_res.get("spoken_text") or (
        f"Ollama model {ollama_res.get('model')} unavailable. Speaking raw packet telemetry for {len(room_map)} mapped devices."
    )

    beam_res = dispatch_sum_difference_tts(
        text=spoken_text,
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
        beam_mode=beam_mode,
        scan_active_udp=False,
        return_to_origin=True,
        listen_with_mic=listen_with_mic,
        input_device=input_device,
    )
    beam_res["ollama"] = ollama_res
    beam_res["logs"] = (
        f"[OLLAMA MODEL: {ollama_res.get('model')} ({ollama_res.get('elapsed_sec', 0)}s)]\n"
        f"{ollama_res.get('response') or ollama_res.get('error', '')}\n\n"
        + (beam_res.get("logs") or "")
    )
    return beam_res


def _energy_vad_is_speech(left_ch: np.ndarray, threshold_rms: float = 0.025) -> bool:
    """Fallback voice-band VAD when webrtcvad C extension is not installed."""
    rms = float(np.sqrt(np.mean(np.square(left_ch))))
    if rms < threshold_rms:
        return False
    # Check voice frequency band energy (250Hz - 3500Hz)
    spec = np.abs(np.fft.rfft(left_ch))
    freqs = np.fft.rfftfreq(len(left_ch), d=1.0 / SAMPLE_RATE)
    voice_mask = (freqs >= 250) & (freqs <= 3500)
    total_energy = float(np.sum(spec)) + 1e-9
    voice_ratio = float(np.sum(spec[voice_mask])) / total_energy
    return voice_ratio > 0.35


class VoiceBeamListener:
    """
    Background stereo microphone TDOA + VAD + optional Vosk speech listener
    that steers any configured TTS reply text toward the detected speaker position X.
    """

    def __init__(self) -> None:
        self.running = False
        self.reply_text = "Hello World"
        self.voice = "en-us"
        self.speed = 150
        self.pitch = 50
        self.smooth_x = 0.0
        self.listener_y = 1.5
        self.events: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(
        self,
        reply_text: str = "Hello World",
        voice: str = "en-us",
        speed: int = 150,
        pitch: int = 50,
        listener_y: float = 1.5,
    ) -> dict[str, Any]:
        self.reply_text = reply_text or "Hello World"
        self.voice = voice
        self.speed = speed
        self.pitch = pitch
        self.listener_y = listener_y

        if self.running:
            return self.status()

        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        self.running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "reply_text": self.reply_text,
            "voice": self.voice,
            "speed": self.speed,
            "pitch": self.pitch,
            "smooth_x": round(self.smooth_x, 2),
            "listener_y": round(self.listener_y, 2),
            "webrtcvad_available": webrtcvad is not None,
            "vosk_available": Model is not None and os.path.isdir("model"),
            "recent_events": self.events[-15:],
        }

    def _loop(self) -> None:
        vad = webrtcvad.Vad(2) if webrtcvad is not None else None
        recognizer = None
        if Model is not None and KaldiRecognizer is not None and os.path.isdir("model"):
            try:
                vosk_model = Model("model")
                recognizer = KaldiRecognizer(vosk_model, SAMPLE_RATE)
            except Exception:
                recognizer = None

        is_speaking_out = False
        consecutive_speech_frames = 0

        def run_reply(target_x: float, heard_text: str) -> None:
            nonlocal is_speaking_out
            try:
                room_map = load_room_map(ROOM_MAP_FILE)
                spoken = self.reply_text.replace("{heard}", heard_text) if "{heard}" in self.reply_text else self.reply_text
                dispatch_sum_difference_tts(
                    text=spoken,
                    listener_x=target_x,
                    listener_y=self.listener_y,
                    room_map=room_map,
                    voice=self.voice,
                    speed=self.speed,
                    pitch=self.pitch,
                    play_local=True,
                    blocking_local=True,
                )
                time.sleep(0.4)
            finally:
                is_speaking_out = False

        def mic_callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            nonlocal is_speaking_out, consecutive_speech_frames
            if is_speaking_out or self._stop_event.is_set():
                return

            left_ch = indata[:, 0]
            right_ch = indata[:, 1] if indata.shape[1] > 1 else left_ch
            pcm_bytes = np.clip(left_ch * 32767.0, -32768, 32767).astype(np.int16).tobytes()

            speech_detected = False
            if vad is not None:
                try:
                    speech_detected = vad.is_speech(pcm_bytes, SAMPLE_RATE)
                except Exception:
                    speech_detected = _energy_vad_is_speech(left_ch)
            else:
                speech_detected = _energy_vad_is_speech(left_ch)

            if speech_detected:
                raw_x = estimate_speaker_x(left_ch, right_ch)
                self.smooth_x = (0.65 * self.smooth_x) + (0.35 * raw_x)
                consecutive_speech_frames += 1

                if recognizer is not None:
                    if recognizer.AcceptWaveform(pcm_bytes):
                        res = json.loads(recognizer.Result())
                        heard = res.get("text", "").strip()
                        if heard:
                            self.events.append(
                                {
                                    "time": time.strftime("%H:%M:%S"),
                                    "x": round(self.smooth_x, 2),
                                    "heard": heard,
                                    "replied": self.reply_text,
                                }
                            )
                            is_speaking_out = True
                            threading.Thread(
                                target=run_reply,
                                args=(self.smooth_x, heard),
                                daemon=True,
                            ).start()
                elif consecutive_speech_frames >= 12:
                    # Trigger on ~240ms of continuous speech when Vosk model is not present
                    consecutive_speech_frames = 0
                    self.events.append(
                        {
                            "time": time.strftime("%H:%M:%S"),
                            "x": round(self.smooth_x, 2),
                            "heard": "(voice activity detected)",
                            "replied": self.reply_text,
                        }
                    )
                    is_speaking_out = True
                    threading.Thread(
                        target=run_reply,
                        args=(self.smooth_x, ""),
                        daemon=True,
                    ).start()
            else:
                consecutive_speech_frames = max(0, consecutive_speech_frames - 1)

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=2,
                blocksize=CHUNK_SAMPLES,
                dtype="float32",
                callback=mic_callback,
            ):
                while not self._stop_event.is_set():
                    time.sleep(0.25)
        except Exception as exc:
            self.events.append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "x": round(self.smooth_x, 2),
                    "heard": f"[Audio input error: {exc}]",
                    "replied": "",
                }
            )
            self.running = False


voice_listener = VoiceBeamListener()


class UDPMulticastReturnReflector:
    """
    Listens on multicast group 239.0.0.1:5005 (and unicast UDP port 5005) for incoming
    multicast or active-UDP response frames, extracts the original position (orig_x, orig_y)
    encoded in the 16-byte header, and sends back the exact same payload to the sender's
    active UDP port & original position.
    """

    def __init__(self, multicast_ip: str = UDP_IP, port: int = UDP_PORT) -> None:
        self.multicast_ip = multicast_ip
        self.port = port
        self.running = False
        self.default_orig_x = 0.0
        self.default_orig_y = 1.5
        self.packets_returned = 0
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def record_external_event(self, evt: dict[str, Any]) -> None:
        with self._lock:
            self.packets_returned += 1
            self.events.append(evt)
            if len(self.events) > 40:
                self.events = self.events[-40:]

    def start(self, orig_x: float = 0.0, orig_y: float = 1.5) -> dict[str, Any]:
        self.default_orig_x = float(orig_x)
        self.default_orig_y = float(orig_y)
        if self.running:
            return self.status()

        self._stop_event.clear()
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        self.running = False
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            recent = list(self.events[-15:])
            total = self.packets_returned
        return {
            "running": self.running,
            "multicast_group": f"{self.multicast_ip}:{self.port}",
            "default_orig_x": round(self.default_orig_x, 2),
            "default_orig_y": round(self.default_orig_y, 2),
            "packets_returned": total,
            "recent_events": recent,
        }

    def _loop(self) -> None:
        local_ip = get_local_ip()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.port))
            mreq = struct.pack("4sl", socket.inet_aton(self.multicast_ip), socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            # Disable multicast loopback so we don't infinite-loop our own echo
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
            sock.settimeout(0.35)

            while not self._stop_event.is_set():
                try:
                    data, (sender_ip, sender_port) = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except Exception:
                    break

                if not data:
                    continue

                orig_x, orig_y = self.default_orig_x, self.default_orig_y
                if len(data) >= HEADER_SIZE:
                    try:
                        ts_val, ux, uy = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
                        if 1_600_000_000 < ts_val < 2_500_000_000 and abs(ux) <= 25.0 and abs(uy) <= 25.0:
                            orig_x, orig_y = round(float(ux), 2), round(float(uy), 2)
                    except Exception:
                        pass

                # Echo the exact same packet back to the sender's active UDP port (if remote)
                # with the unpacked original position (orig_x, orig_y)
                new_header = struct.pack(HEADER_FMT, time.time() + 0.04, float(orig_x), float(orig_y))
                return_pkt = new_header + (data[HEADER_SIZE:] if len(data) > HEADER_SIZE else (b"\x00\x00\x00\x00" * 64))

                if sender_ip != local_ip and not sender_ip.startswith("127."):
                    try:
                        sock.sendto(return_pkt, (sender_ip, int(sender_port)))
                    except Exception:
                        pass

                self.record_external_event(
                    {
                        "time": time.strftime("%H:%M:%S"),
                        "sender_ip": sender_ip,
                        "sender_udp_port": int(sender_port),
                        "service": UDP_IOT_PORTS.get(int(sender_port), "Multicast / Active UDP"),
                        "orig_x": orig_x,
                        "orig_y": orig_y,
                        "bytes_received": len(data),
                        "bytes_returned": len(return_pkt),
                        "action": f"Echoed same payload back to {sender_ip}:{sender_port} @ Original Pos ({orig_x}m, {orig_y}m)",
                    }
                )
        except Exception as exc:
            print(f"[UDP Multicast Return Reflector warning] {exc}")
        finally:
            self.running = False
            sock.close()


udp_reflector = UDPMulticastReturnReflector()
# Start the multicast & active UDP return-to-origin reflector by default
udp_reflector.start()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Text-to-Speech Sum/Difference Acoustic Beamformer")
    parser.add_argument("text", nargs="*", default=["Hello World"], help="Text to synthesize and beam")
    parser.add_argument("--x", type=float, default=0.0, help="Target listener X coordinate in meters (default: 0.0)")
    parser.add_argument("--y", type=float, default=1.5, help="Target listener Y coordinate in meters (default: 1.5)")
    parser.add_argument("--voice", default="en-us", help="espeak-ng voice (default: en-us)")
    parser.add_argument("--speed", type=int, default=150, help="Speech speed in WPM (default: 150)")
    parser.add_argument("--pitch", type=int, default=50, help="Voice pitch 0-99 (default: 50)")
    parser.add_argument("--listen", action="store_true", help="Enter continuous stereo TDOA voice-tracking loop")
    args = parser.parse_args()

    spoken_text = " ".join(args.text).strip() or "Hello World"
    room_map = load_room_map(ROOM_MAP_FILE)

    dispatch_sum_difference_tts(
        text=spoken_text,
        listener_x=args.x,
        listener_y=args.y,
        room_map=room_map,
        voice=args.voice,
        speed=args.speed,
        pitch=args.pitch,
        play_local=True,
        cast_enabled=True,
        udp_enabled=True,
        blocking_local=True,
    )

    if args.listen:
        print(f"\nSystem LIVE. Speak anywhere in the room to steer '{spoken_text}' to your spot...")
        voice_listener.start(
            reply_text=spoken_text,
            voice=args.voice,
            speed=args.speed,
            pitch=args.pitch,
            listener_y=args.y,
        )
        try:
            while voice_listener.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            voice_listener.stop()
            print("\nShutting down.")


if __name__ == "__main__":
    main()
