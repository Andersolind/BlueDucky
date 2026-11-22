import concurrent.futures
import ipaddress
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any

import pychromecast
import requests
from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

# Common IoT & Smart Device OUI prefixes (first 3 bytes of MAC)
OUI_VENDORS = {
    "00:1A:11": "Google",
    "3C:5A:B4": "Google",
    "54:60:09": "Google",
    "A4:77:33": "Google",
    "F4:F5:D8": "Google",
    "F4:F5:E8": "Google",
    "48:D6:D5": "Google",
    "D8:6C:63": "Google",
    "E4:F0:42": "Google",
    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi",
    "24:0A:C4": "Espressif (ESP32/ESP8266)",
    "30:AE:A4": "Espressif (ESP32/ESP8266)",
    "84:CCA8": "Espressif (ESP32/ESP8266)",
    "A0:20:A6": "Espressif (ESP32/ESP8266)",
    "B4:E6:2D": "Espressif (ESP32/ESP8266)",
    "00:17:88": "Philips Hue",
    "EC:B5:FA": "Philips Hue",
    "00:0E:58": "Sonos",
    "5C:AA:FD": "Sonos",
    "78:28:CA": "Sonos",
    "94:9F:3E": "Sonos",
    "B8:E9:37": "Sonos",
    "B0:A7:37": "Roku",
    "D8:31:34": "Roku",
    "CC:6D:A0": "Roku",
    "AC:3A:7A": "Roku",
    "50:C7:BF": "TP-Link",
    "B0:4E:26": "TP-Link",
    "68:FF:7B": "TP-Link",
    "FC:EC:DA": "Ubiquiti",
    "74:83:C2": "Ubiquiti",
    "24:5A:4C": "Ubiquiti",
}

IOT_PORTS = {
    80: "HTTP Web UI",
    443: "HTTPS Web UI",
    554: "RTSP Camera/Stream",
    1400: "Sonos UPnP",
    1883: "MQTT Broker",
    5000: "UPnP / Synology / AirPlay",
    7000: "AirPlay Receiver",
    8008: "Google Cast HTTP",
    8009: "Google Cast TLS",
    8060: "Roku ECP",
    8443: "HTTPS Alt",
    9000: "Media / Smart Home",
    62078: "Apple iOS Sync",
}

UDP_IOT_PORTS = {
    7: "UDP Echo",
    137: "NetBIOS Name",
    161: "SNMP",
    1900: "SSDP / UPnP Multicast",
    3702: "WS-Discovery",
    5000: "UPnP / AirPlay Control UDP",
    5004: "RTP Media Stream",
    5005: "Beamformer / RTCP Audio",
    5353: "mDNS / Zeroconf",
    5683: "CoAP IoT",
    6000: "AirPlay Audio Data",
    6001: "AirPlay Retransmit UDP",
    6002: "AirPlay Timing UDP",
    7000: "AirPlay Receiver UDP",
    8008: "Google Cast UDP",
    8009: "Google Cast TLS/UDP",
    10001: "Ubiquiti Discovery",
}

MDNS_SERVICES = [
    ("_googlecast._tcp.local.", "Google Cast"),
    ("_airplay._tcp.local.", "Apple AirPlay"),
    ("_raop._tcp.local.", "AirPlay Audio (RAOP)"),
    ("_hap._tcp.local.", "Apple HomeKit"),
    ("_matter._tcp.local.", "Matter Smart Home"),
    ("_matterc._udp.local.", "Matter Commissioning"),
    ("_spotify-connect._tcp.local.", "Spotify Connect"),
    ("_sonos._tcp.local.", "Sonos Audio"),
    ("_ipp._tcp.local.", "Network Printer (IPP)"),
    ("_printer._tcp.local.", "Network Printer"),
    ("_esphomelib._tcp.local.", "ESPHome IoT"),
    ("_hue._tcp.local.", "Philips Hue Bridge"),
    ("_http._tcp.local.", "HTTP Web Service"),
    ("_workstation._tcp.local.", "Workstation"),
    ("_companion-link._tcp.local.", "Apple Companion"),
]


def is_ipv4_address(ip: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(str(ip).split("%")[0]), ipaddress.IPv4Address)
    except Exception:
        return False


def ip_sort_key(ip: str) -> tuple[int, ...]:
    try:
        addr = ipaddress.ip_address(str(ip).split("%")[0])
        return (addr.version, *addr.packed)
    except Exception:
        return (99, 999, 999, 999, 999)


def lookup_mac_vendor(mac: str) -> str:
    if not mac:
        return ""
    norm = mac.upper().replace("-", ":")
    prefix = norm[:8]
    return OUI_VENDORS.get(prefix, "")


def extract_device_packet_words(
    name: str,
    ip: str,
    mac: str = "",
    vendor: str = "",
    model: str = "",
    protocols: list[str] | None = None,
    udp_ports: list[int] | None = None,
    confirmed_udp_ports: list[int] | None = None,
    sources: list[dict[str, Any]] | None = None,
    multicast_hits: list[dict[str, Any]] | None = None,
    arp_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Decode human-readable digital words from a device's MAC address, OUI vendor,
    hostname, mDNS/SSDP metadata, and live UDP packet payload previews.
    """
    if arp_map is None:
        arp_map = _read_arp_table()

    resolved_ip, resolved_mac = resolve_ipv6_to_ipv4(ip, arp_map)
    mac_val = (mac or resolved_mac or arp_map.get(ip, "") or arp_map.get(resolved_ip, "")).upper().replace("-", ":")

    # Check if hostname embeds a 12-hex-digit MAC (e.g. BOSCH-B36CL81ENG-68A40E885B06)
    hex12_match = re.search(r"(?:^|[-_])([0-9A-Fa-f]{12})(?:$|[-_])", name or "")
    if hex12_match and not mac_val:
        raw_hex = hex12_match.group(1).upper()
        mac_val = ":".join(raw_hex[i : i + 2] for i in range(0, 12, 2))

    vendor_val = vendor or lookup_mac_vendor(mac_val)
    if not vendor_val:
        lower_name = (name or "").lower()
        for brand in ("samsung", "bosch", "nest", "google", "sonos", "roku", "apple", "philips", "hp", "tp-link", "ubiquiti"):
            if brand in lower_name:
                vendor_val = brand.capitalize()
                break

    # Clean hostname into natural spoken words
    clean_name = (name or ip).strip()
    if clean_name == "_gateway":
        clean_name = "Gateway Router"
    else:
        if hex12_match:
            clean_name = clean_name.replace(hex12_match.group(1), "").strip("-_ ")
        clean_name = re.sub(r"[-_]+", " ", clean_name).strip() or ip

    # Build MAC spoken tokens
    mac_words: list[str] = []
    if vendor_val:
        mac_words.append(f"Vendor {vendor_val}")
    if mac_val:
        octets = mac_val.split(":")
        mac_words.append(f"MAC {' '.join(octets)}")
        mac_short = f"MAC ending {' '.join(octets[-2:])}"
    else:
        mac_short = f"IP ending {resolved_ip.split('.')[-1]}" if is_ipv4_address(resolved_ip) else "IPv6 Node"

    # Extract readable digital words from packet sources & live UDP replies
    packet_tokens: list[str] = []
    seen_lower: set[str] = set()

    def _add_token(tok: str) -> None:
        t = re.sub(r"[-_/]+", " ", tok).strip(" .,:;\"'()[]{}")
        if not t or len(t) < 2:
            return
        tl = t.lower()
        if tl in seen_lower or tl in ("http", "1.1", "200", "ok", "true", "false", "null", "none", "local", "tcp", "udp"):
            return
        seen_lower.add(tl)
        packet_tokens.append(t)

    _add_token(clean_name)
    if vendor_val:
        _add_token(vendor_val)

    if model and not model.startswith(("Active UDP Host", "Network Host", "UDP Multicast Responder")):
        _add_token(model)

    for src in sources or []:
        det = src.get("details") or {}
        if isinstance(det.get("properties"), dict):
            for pk in ("fn", "md", "ty", "am", "manufacturer", "model"):
                if det["properties"].get(pk):
                    _add_token(str(det["properties"][pk]))
        for dk in ("server", "st", "device_type", "service_type", "hostname"):
            val = det.get(dk)
            if val and isinstance(val, str):
                # Pull readable words out of server/service strings
                words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", val)
                if words:
                    _add_token(" ".join(words[:4]))
        for mhit in det.get("multicast_replies") or []:
            prev = str(mhit.get("preview") or "")
            words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", prev) if w.upper() not in ("HTTP", "CACHE", "CONTROL", "MAX", "AGE", "EXT", "DATE", "GMT")]
            if words:
                _add_token(" ".join(words[:5]))

    for mhit in multicast_hits or []:
        prev = str(mhit.get("preview") or "")
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", prev) if w.upper() not in ("HTTP", "CACHE", "CONTROL", "MAX", "AGE", "EXT", "DATE", "GMT")]
        if words:
            _add_token(" ".join(words[:5]))

    # Add UDP service descriptors
    active_ports = confirmed_udp_ports or (udp_ports or [])[:3]
    for p in active_ports[:3]:
        svc = UDP_IOT_PORTS.get(int(p), f"UDP {p}")
        _add_token(f"UDP {p} {svc.split('/')[0].strip()}")

    for proto in protocols or []:
        _add_token(proto.split("/")[0].strip())

    digital_words_str = ", ".join(packet_tokens[:6]) if packet_tokens else clean_name
    mac_clause = f"{vendor_val + ' ' if vendor_val else ''}{mac_short}" if (mac_val or vendor_val) else mac_short

    spoken_text = (
        f"IoT device {clean_name}. {mac_clause}. "
        f"Digital packet words: {digital_words_str}."
    )
    short_spoken_text = f"{clean_name}, {mac_short}, packet words: {', '.join(packet_tokens[:3])}."

    return {
        "mac": mac_val,
        "vendor": vendor_val,
        "clean_name": clean_name,
        "mac_words": mac_words,
        "packet_words": packet_tokens,
        "spoken_text": spoken_text,
        "short_spoken_text": short_spoken_text,
    }


def get_local_ip_and_subnet() -> tuple[str, ipaddress.IPv4Network]:
    """Determine active local IPv4 address and /24 subnet."""
    local_ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
    except Exception:
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            pass

    if local_ip.startswith("127."):
        # Fallback: inspect ip -4 addr
        try:
            out = subprocess.check_output(["ip", "-4", "-o", "addr", "show"], text=True, timeout=2)
            for line in out.splitlines():
                if "scope global" in line:
                    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
                    if m:
                        local_ip = m.group(1)
                        break
        except Exception:
            pass

    net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
    return local_ip, net


def scan_chromecast(timeout: float = 5.0) -> list[dict[str, Any]]:
    """
    Discover Google Cast / Chromecast devices using pychromecast.
    Starts directly from the user's pychromecast snippet.
    """
    results: list[dict[str, Any]] = []
    browser = None
    try:
        print("Scanning Wi-Fi for smart speakers and TVs...")
        chromecasts, browser = pychromecast.get_chromecasts(timeout=timeout, tries=1)

        for cc in chromecasts:
            host = getattr(cc.cast_info, "host", None) or getattr(cc, "uri", "").split(":")[0]
            port = getattr(cc.cast_info, "port", 8009)
            print(f"Found IoT Device: {cc.name} | IP: {host} | Model: {cc.model_name}")
            results.append(
                {
                    "name": cc.name or "Chromecast Device",
                    "ip": host,
                    "port": port,
                    "model": cc.model_name or "Google Cast",
                    "manufacturer": getattr(cc.cast_info, "manufacturer", None) or "Google",
                    "protocol": "Chromecast",
                    "category": f"Cast ({getattr(cc, 'cast_type', 'cast') or 'device'})",
                    "uuid": str(getattr(cc, "uuid", "")),
                    "details": {
                        "cast_type": getattr(cc, "cast_type", None),
                        "app": getattr(cc, "app_display_name", None),
                        "uuid": str(getattr(cc, "uuid", "")),
                        "port": port,
                    },
                }
            )
    except Exception as exc:
        print(f"[Chromecast scan warning] {exc}")
    finally:
        if browser is not None:
            try:
                browser.stop_discovery()
            except Exception:
                pass

    return results


def _fetch_upnp_description(location_url: str, timeout: float = 1.5) -> dict[str, str]:
    """Fetch and parse UPnP XML device description for friendlyName, modelName, manufacturer."""
    info: dict[str, str] = {}
    if not location_url or not location_url.startswith(("http://", "https://")):
        return info
    try:
        resp = requests.get(location_url, timeout=timeout, headers={"User-Agent": "DiscoveryChannel/1.0"})
        if resp.status_code == 200 and resp.text:
            root = ET.fromstring(resp.text)
            for elem in root.iter():
                tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                text = (elem.text or "").strip()
                if not text:
                    continue
                if tag == "friendlyName" and "friendlyName" not in info:
                    info["friendlyName"] = text
                elif tag == "modelName" and "modelName" not in info:
                    info["modelName"] = text
                elif tag == "manufacturer" and "manufacturer" not in info:
                    info["manufacturer"] = text
                elif tag == "deviceType" and "deviceType" not in info:
                    info["deviceType"] = text
    except Exception:
        pass
    return info


def scan_ssdp(timeout: float = 3.5) -> list[dict[str, Any]]:
    """
    Discover UPnP / SSDP Smart TVs, Roku, DLNA media renderers, routers, and speakers.
    """
    ssdp_addr = ("239.255.255.250", 1900)
    search_targets = ["ssdp:all", "upnp:rootdevice", "urn:dial-multiscreen-org:service:dial:1", "roku:ecp"]

    raw_hits: dict[str, dict[str, Any]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)

    try:
        for st in search_targets:
            msg = (
                "M-SEARCH * HTTP/1.1\r\n"
                f"HOST: {ssdp_addr[0]}:{ssdp_addr[1]}\r\n"
                'MAN: "ssdp:discover"\r\n'
                "MX: 2\r\n"
                f"ST: {st}\r\n"
                "\r\n"
            ).encode("utf-8")
            try:
                sock.sendto(msg, ssdp_addr)
            except Exception:
                pass

        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception:
                break

            ip, port = addr[0], addr[1]
            text = data.decode("utf-8", errors="ignore")
            headers: dict[str, str] = {}
            for line in text.splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().upper()] = v.strip()

            location = headers.get("LOCATION", "")
            server = headers.get("SERVER", "")
            st = headers.get("ST", "")
            usn = headers.get("USN", "")

            entry = raw_hits.setdefault(
                ip,
                {
                    "ip": ip,
                    "port": port,
                    "location": location,
                    "server": server,
                    "st": st,
                    "usn": usn,
                },
            )
            if location and not entry["location"]:
                entry["location"] = location
            if server and not entry["server"]:
                entry["server"] = server
    finally:
        sock.close()

    results: list[dict[str, Any]] = []
    # Fetch UPnP XML descriptions concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        future_map = {
            pool.submit(_fetch_upnp_description, hit["location"]): ip
            for ip, hit in raw_hits.items()
            if hit.get("location")
        }
        xml_infos: dict[str, dict[str, str]] = {}
        for fut in concurrent.futures.as_completed(future_map):
            ip = future_map[fut]
            try:
                xml_infos[ip] = fut.result()
            except Exception:
                xml_infos[ip] = {}

    for ip, hit in raw_hits.items():
        xml = xml_infos.get(ip, {})
        name = xml.get("friendlyName") or hit.get("server") or f"UPnP Device ({ip})"
        model = xml.get("modelName") or hit.get("st") or "UPnP / SSDP"
        manufacturer = xml.get("manufacturer") or ""
        results.append(
            {
                "name": name,
                "ip": ip,
                "port": hit["port"],
                "model": model,
                "manufacturer": manufacturer,
                "protocol": "SSDP / UPnP",
                "category": "Smart TV / Media / UPnP",
                "details": {
                    "location": hit.get("location"),
                    "server": hit.get("server"),
                    "st": hit.get("st"),
                    "usn": hit.get("usn"),
                    "device_type": xml.get("deviceType"),
                },
            }
        )

    return results


class _MDNSCollector(ServiceListener):
    def __init__(self, zc: Zeroconf, label_map: dict[str, str]) -> None:
        self.zc = zc
        self.label_map = label_map
        self.lock = threading.Lock()
        self.records: list[dict[str, Any]] = []

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._resolve(zc, type_, name)

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        self._resolve(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        pass

    def _resolve(self, zc: Zeroconf, type_: str, name: str) -> None:
        try:
            info: ServiceInfo | None = zc.get_service_info(type_, name, timeout=1500)
        except Exception:
            info = None
        if not info:
            return

        addrs = info.parsed_addresses(IPVersion.V4Only)
        if not addrs:
            addrs = info.parsed_addresses()
        if not addrs:
            return

        ip = addrs[0]
        props: dict[str, str] = {}
        if info.properties:
            for k, v in info.properties.items():
                key = k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)
                val = v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else str(v)
                props[key] = val

        short_name = name.replace(f".{type_}", "")
        friendly = props.get("fn") or props.get("ty") or short_name
        model = (
            props.get("md")
            or props.get("model")
            or props.get("am")
            or self.label_map.get(type_, type_)
        )
        manufacturer = props.get("usb_MFG") or props.get("manufacturer") or ""

        record = {
            "name": friendly,
            "ip": ip,
            "port": info.port,
            "model": model,
            "manufacturer": manufacturer,
            "protocol": "mDNS / Zeroconf",
            "category": self.label_map.get(type_, "mDNS Service"),
            "details": {
                "service_type": type_,
                "service_name": name,
                "server": info.server,
                "port": info.port,
                "properties": props,
            },
        }
        with self.lock:
            self.records.append(record)


def scan_mdns(timeout: float = 4.0) -> list[dict[str, Any]]:
    """
    Discover mDNS / Zeroconf smart home, AirPlay, HomeKit, Cast, Sonos, and printer devices.
    """
    zc = None
    try:
        zc = Zeroconf(ip_version=IPVersion.V4Only)
        label_map = dict(MDNS_SERVICES)
        collector = _MDNSCollector(zc, label_map)
        service_types = [s[0] for s in MDNS_SERVICES]
        browser = ServiceBrowser(zc, service_types, collector)
        time.sleep(timeout)
        browser.cancel()
        return collector.records
    except Exception as exc:
        print(f"[mDNS scan warning] {exc}")
        return []
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass


def _probe_host(ip: str, ports: tuple[int, ...] = (80, 443, 8008, 8009, 8060, 7000, 1400, 554, 1883)) -> list[int]:
    """Quick TCP connect probe to wake ARP entry and check common IoT ports."""
    open_ports: list[int] = []
    for p in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.22)
                res = s.connect_ex((ip, p))
                if res == 0:
                    open_ports.append(p)
        except Exception:
            pass
    return open_ports


def _read_arp_table() -> dict[str, str]:
    """Return mapping of IP -> MAC address from /proc/net/arp and `ip neigh`."""
    ip_to_mac: dict[str, str] = {}
    try:
        with open("/proc/net/arp", "r", encoding="utf-8") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    ip, mac = parts[0], parts[3]
                    if mac != "00:00:00:00:00:00" and ":" in mac:
                        ip_to_mac[ip] = mac.upper()
    except Exception:
        pass

    try:
        out = subprocess.check_output(["ip", "neigh", "show"], text=True, timeout=2)
        for line in out.splitlines():
            m = re.match(r"^(\S+)\s+.*lladdr\s+([0-9a-fA-F:]{17})", line)
            if m:
                ip_to_mac[m.group(1)] = m.group(2).upper()
    except Exception:
        pass

    return ip_to_mac


def resolve_ipv6_to_ipv4(ip: str, arp_map: dict[str, str] | None = None) -> tuple[str, str]:
    """
    If `ip` is an IPv6 address (e.g. link-local fe80::... from Matter/mDNS), extract its MAC
    from `ip neigh` or IEEE EUI-64 (ff:fe) and map it to its IPv4 address if known in ARP.
    Returns (best_ip, mac).
    """
    clean_ip = str(ip).split("%")[0]
    if is_ipv4_address(clean_ip):
        if arp_map is None:
            arp_map = _read_arp_table()
        return clean_ip, arp_map.get(clean_ip, "")

    if arp_map is None:
        arp_map = _read_arp_table()

    mac = arp_map.get(clean_ip, "")
    if not mac:
        try:
            addr6 = ipaddress.IPv6Address(clean_ip)
            b = addr6.packed
            if b[11] == 0xFF and b[12] == 0xFE:
                mac_bytes = [b[8] ^ 0x02, b[9], b[10], b[13], b[14], b[15]]
                mac = ":".join(f"{x:02X}" for x in mac_bytes)
        except Exception:
            pass

    if mac:
        for candidate_ip, candidate_mac in arp_map.items():
            if candidate_mac == mac and is_ipv4_address(candidate_ip):
                return candidate_ip, mac

    return clean_ip, mac


def scan_lan_arp(timeout: float = 3.0) -> list[dict[str, Any]]:
    """
    Scan local /24 network using ARP neighbor cache + fast concurrent IoT TCP port probe.
    """
    local_ip, subnet = get_local_ip_and_subnet()
    hosts = [str(ip) for ip in subnet.hosts() if str(ip) != local_ip]

    open_ports_by_ip: dict[str, list[int]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        fut_to_ip = {pool.submit(_probe_host, ip): ip for ip in hosts}
        try:
            for fut in concurrent.futures.as_completed(fut_to_ip, timeout=timeout + 2.0):
                ip = fut_to_ip[fut]
                try:
                    ports = fut.result()
                    if ports:
                        open_ports_by_ip[ip] = ports
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            pass

    arp_map = _read_arp_table()
    discovered_ips = sorted(
        {ip for ip in (set(arp_map.keys()) | set(open_ports_by_ip.keys())) if is_ipv4_address(ip)},
        key=ip_sort_key,
    )

    results: list[dict[str, Any]] = []
    for ip in discovered_ips:
        if not ipaddress.IPv4Address(ip) in subnet:
            continue
        mac = arp_map.get(ip, "")
        vendor = lookup_mac_vendor(mac)
        ports = open_ports_by_ip.get(ip, [])
        port_labels = [f"{p} ({IOT_PORTS.get(p, 'TCP')})" for p in ports]

        hostname = ""
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass

        # Infer model / category from open IoT ports
        inferred_model = "Network Host"
        if 8008 in ports or 8009 in ports:
            inferred_model = "Google Cast / Smart Speaker"
        elif 8060 in ports:
            inferred_model = "Roku Streaming Device"
        elif 1400 in ports:
            inferred_model = "Sonos Speaker"
        elif 7000 in ports or 62078 in ports:
            inferred_model = "Apple / AirPlay Device"
        elif 554 in ports:
            inferred_model = "RTSP IP Camera / Media"
        elif 1883 in ports:
            inferred_model = "MQTT IoT Hub"
        elif ports:
            inferred_model = f"Active Host ({', '.join(map(str, ports))})"

        display_name = hostname or (f"{vendor} Device ({ip})" if vendor else f"LAN Device ({ip})")
        results.append(
            {
                "name": display_name,
                "ip": ip,
                "port": ports[0] if ports else None,
                "model": inferred_model,
                "manufacturer": vendor,
                "mac": mac,
                "protocol": "LAN / ARP",
                "category": "Local Network Device",
                "details": {
                    "mac": mac,
                    "hostname": hostname,
                    "open_ports": ports,
                    "services": port_labels,
                },
            }
        )

    return results


def send_multicast_wakeup_and_capture(
    timeout: float = 1.2,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
) -> dict[str, list[dict[str, Any]]]:
    """
    Send the beamformer UDP position multicast (239.0.0.1:5005), SSDP M-SEARCH (239.255.255.250:1900),
    and mDNS query (224.0.0.251:5353), then capture every host & active UDP source port that replies
    back to our sender socket.
    """
    local_ip, _ = get_local_ip_and_subnet()
    replies_by_ip: dict[str, list[dict[str, Any]]] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.25)

    try:
        # 1. Beamformer audio multicast header carrying original position (timestamp, listener_x, listener_y)
        beam_header = struct.pack("dff", time.time() + 0.04, float(listener_x), float(listener_y))
        beam_pulse = beam_header + (b"\x00\x00\x00\x00" * 64)
        try:
            sock.sendto(beam_pulse, ("239.0.0.1", 5005))
        except Exception:
            pass

        # 2. SSDP multicast wake-up (239.255.255.250:1900)
        ssdp_msg = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1900\r\n"
            'MAN: "ssdp:discover"\r\n'
            "MX: 1\r\n"
            "ST: ssdp:all\r\n\r\n"
        ).encode("utf-8")
        try:
            sock.sendto(ssdp_msg, ("239.255.255.250", 1900))
        except Exception:
            pass

        # 3. mDNS DNS-SD multicast wake-up (224.0.0.251:5353)
        mdns_query = (
            b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
            b"\x09_services\x07_dns-sd\x04_udp\x05local\x00"
            b"\x00\x0c\x00\x01"
        )
        try:
            sock.sendto(mdns_query, ("224.0.0.251", 5353))
        except Exception:
            pass

        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except Exception:
                break

            ip, src_port = addr[0], int(addr[1])
            if ip == local_ip or ip.startswith("127."):
                continue
            replies_by_ip.setdefault(ip, []).append(
                {
                    "udp_port": src_port,
                    "bytes": len(data),
                    "service": UDP_IOT_PORTS.get(src_port, "Active Multicast Responder"),
                    "preview": data[:80].decode("utf-8", errors="ignore").strip(),
                }
            )
    finally:
        sock.close()

    return replies_by_ip


def _run_nmap_udp_scan(
    target_ips: list[str],
    ports_str: str = "7,137,161,1900,3702,5000,5004,5005,5353,5683,6000-6002,7000,8008,8009",
    timeout: float = 5.0,
) -> tuple[dict[str, dict[str, Any]], str]:
    """
    Execute `nmap -sU` against discovered target IPs right after the multicast wake-up.
    Returns (nmap_by_ip, nmap_command_line).
    """
    nmap_bin = shutil.which("nmap") or "/usr/bin/nmap"
    ipv4_targets = [ip for ip in target_ips if is_ipv4_address(ip)]
    if not ipv4_targets or not nmap_bin:
        return {}, ""

    cmd = [
        nmap_bin,
        "-sU",
        "-n",
        "-Pn",
        "-T4",
        "--max-retries",
        "1",
        "--host-timeout",
        f"{max(2, int(timeout))}s",
        "-p",
        ports_str,
        "-oX",
        "-",
        *ipv4_targets,
    ]
    cmd_str = " ".join(cmd)
    nmap_by_ip: dict[str, dict[str, Any]] = {}

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(4.0, timeout + 3.0),
        )
        xml_out = proc.stdout
        if xml_out and "<nmaprun" in xml_out:
            root = ET.fromstring(xml_out)
            for host_el in root.findall("host"):
                ip = ""
                for addr_el in host_el.findall("address"):
                    if addr_el.get("addrtype") == "ipv4":
                        ip = addr_el.get("addr", "")
                        break
                if not ip:
                    continue

                open_udp: list[int] = []
                open_filtered_udp: list[int] = []
                port_details: list[dict[str, Any]] = []

                ports_el = host_el.find("ports")
                if ports_el is not None:
                    for port_el in ports_el.findall("port"):
                        if port_el.get("protocol") != "udp":
                            continue
                        port_id = int(port_el.get("portid", "0"))
                        state_el = port_el.find("state")
                        svc_el = port_el.find("service")
                        state = state_el.get("state", "") if state_el is not None else ""
                        reason = state_el.get("reason", "") if state_el is not None else ""
                        svc_name = (
                            svc_el.get("name", "")
                            if svc_el is not None
                            else UDP_IOT_PORTS.get(port_id, "udp")
                        )

                        if state == "open":
                            open_udp.append(port_id)
                            port_details.append(
                                {
                                    "port": port_id,
                                    "state": state,
                                    "reason": reason,
                                    "service": UDP_IOT_PORTS.get(port_id, svc_name),
                                }
                            )
                        elif state == "open|filtered":
                            open_filtered_udp.append(port_id)
                            port_details.append(
                                {
                                    "port": port_id,
                                    "state": state,
                                    "reason": reason,
                                    "service": UDP_IOT_PORTS.get(port_id, svc_name),
                                }
                            )

                nmap_by_ip[ip] = {
                    "open_udp": sorted(set(open_udp)),
                    "open_filtered_udp": sorted(set(open_filtered_udp)),
                    "port_details": port_details,
                }
    except Exception as exc:
        print(f"[nmap -sU warning] {exc}")

    return nmap_by_ip, cmd_str


def _probe_udp_host_direct(
    ip: str,
    ports: tuple[int, ...] = (7, 1900, 5004, 5005, 5353, 5683, 6000, 6001, 6002),
    listener_x: float = 0.0,
    listener_y: float = 1.5,
) -> dict[str, list[int]]:
    """
    Send direct UDP probe payloads (including the beamformer position header on 5005/7)
    to detect ports that either actively reply or accept UDP datagrams without ICMP Port Unreachable.
    """
    if not is_ipv4_address(ip):
        return {"replied_udp": [], "accepted_udp": []}

    replied: list[int] = []
    accepted: list[int] = []
    beam_payload = struct.pack("dff", time.time() + 0.04, float(listener_x), float(listener_y)) + (b"\x00\x00\x00\x00" * 16)

    for p in ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
                s.settimeout(0.14)
                s.connect((ip, p))
                if p == 1900:
                    payload = (
                        "M-SEARCH * HTTP/1.1\r\n"
                        f"HOST: {ip}:1900\r\n"
                        'MAN: "ssdp:discover"\r\n'
                        "MX: 1\r\n"
                        "ST: upnp:rootdevice\r\n\r\n"
                    ).encode("utf-8")
                elif p == 5353:
                    payload = (
                        b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                        b"\x09_services\x07_dns-sd\x04_udp\x05local\x00\x00\x0c\x00\x01"
                    )
                else:
                    payload = beam_payload

                s.send(payload)
                try:
                    data = s.recv(2048)
                    if data:
                        replied.append(p)
                        accepted.append(p)
                        continue
                except socket.timeout:
                    # Second quick send detects delayed ICMP Port Unreachable (ConnectionRefusedError)
                    try:
                        s.send(payload)
                        time.sleep(0.02)
                        s.send(payload)
                        accepted.append(p)
                    except ConnectionRefusedError:
                        pass
                except ConnectionRefusedError:
                    pass
        except Exception:
            pass

    return {
        "replied_udp": sorted(set(replied)),
        "accepted_udp": sorted(set(accepted)),
    }


def scan_udp_after_multicast(
    timeout: float = 4.5,
    target_ips: list[str] | None = None,
    listener_x: float = 0.0,
    listener_y: float = 1.5,
) -> list[dict[str, Any]]:
    """
    1. Send multicast wake-up (239.0.0.1:5005 position packet, SSDP 1900, mDNS 5353)
       and capture immediate UDP responders + ephemeral source ports.
    2. Run `nmap -sU` and direct UDP probes against all responding / ARP-active hosts.
    3. Return active UDP port records for each host.
    """
    local_ip, subnet = get_local_ip_and_subnet()
    multicast_replies = send_multicast_wakeup_and_capture(
        timeout=min(1.2, timeout * 0.35),
        listener_x=listener_x,
        listener_y=listener_y,
    )

    arp_map = _read_arp_table()
    candidate_set: set[str] = {ip for ip in multicast_replies.keys() if is_ipv4_address(ip)}
    if target_ips:
        candidate_set.update(ip for ip in target_ips if ip and ip != local_ip and is_ipv4_address(ip))
    for ip in arp_map:
        try:
            if ip != local_ip and ipaddress.IPv4Address(ip) in subnet:
                candidate_set.add(ip)
        except Exception:
            pass

    candidates = sorted(candidate_set, key=ip_sort_key)
    nmap_by_ip, nmap_cmd = _run_nmap_udp_scan(candidates, timeout=max(2.5, timeout * 0.7))

    direct_by_ip: dict[str, dict[str, list[int]]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        fut_map = {
            pool.submit(_probe_udp_host_direct, ip, (7, 1900, 5004, 5005, 5353, 5683, 6000, 6001, 6002), listener_x, listener_y): ip
            for ip in candidates
        }
        for fut in concurrent.futures.as_completed(fut_map):
            ip = fut_map[fut]
            try:
                direct_by_ip[ip] = fut.result()
            except Exception:
                direct_by_ip[ip] = {"replied_udp": [], "accepted_udp": []}

    results: list[dict[str, Any]] = []
    for ip in candidates:
        m_hits = multicast_replies.get(ip, [])
        m_ports = [int(h["udp_port"]) for h in m_hits if h.get("udp_port")]
        n_info = nmap_by_ip.get(ip, {})
        d_info = direct_by_ip.get(ip, {})

        confirmed_udp = sorted(
            set(m_ports)
            | set(n_info.get("open_udp", []))
            | set(d_info.get("replied_udp", []))
        )
        open_filtered_udp = sorted(
            set(n_info.get("open_filtered_udp", []))
            | set(d_info.get("accepted_udp", []))
        )
        # Prioritize confirmed UDP responders; always include 5005 + open/accepted UDP ports for beaming
        active_udp = sorted(set(confirmed_udp) | set(open_filtered_udp) | {5005})

        mac = arp_map.get(ip, "")
        vendor = lookup_mac_vendor(mac)
        service_labels = [
            f"UDP/{p} ({UDP_IOT_PORTS.get(p, 'Active Responder')})"
            for p in (confirmed_udp or active_udp[:6])
        ]

        results.append(
            {
                "name": f"{vendor} UDP Node ({ip})" if vendor else f"UDP Responder ({ip})",
                "ip": ip,
                "port": confirmed_udp[0] if confirmed_udp else 5005,
                "model": (
                    f"UDP Multicast Responder ({', '.join(f'UDP/{p}' for p in confirmed_udp)})"
                    if confirmed_udp
                    else f"Active UDP Host ({', '.join(f'UDP/{p}' for p in active_udp[:4])})"
                ),
                "manufacturer": vendor,
                "mac": mac,
                "protocol": "UDP / Nmap",
                "category": "Active UDP / Multicast Node",
                "udp_ports": active_udp,
                "confirmed_udp_ports": confirmed_udp,
                "details": {
                    "nmap_command": nmap_cmd,
                    "confirmed_udp_ports": confirmed_udp,
                    "active_udp_ports": active_udp,
                    "multicast_replies": m_hits,
                    "nmap_ports": n_info.get("port_details", []),
                    "services": service_labels,
                },
            }
        )

    return results


def merge_devices(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Correlate and merge discovered records by IP address so each physical device
    shows its richest name, model, manufacturer, MAC, TCP ports, active UDP ports,
    and all protocols that found it.
    """
    by_ip: dict[str, dict[str, Any]] = {}
    arp_map = _read_arp_table()

    # Priority order for naming: Chromecast > mDNS > SSDP > UDP/Nmap > LAN
    protocol_priority = {
        "Chromecast": 5,
        "mDNS / Zeroconf": 4,
        "SSDP / UPnP": 3,
        "UDP / Nmap": 2,
        "LAN / ARP": 1,
    }

    for item in raw_items:
        raw_ip = item.get("ip") or "unknown"
        ip, resolved_mac = resolve_ipv6_to_ipv4(raw_ip, arp_map)
        if resolved_mac and not item.get("mac"):
            item["mac"] = resolved_mac
        if item.get("mac") and not item.get("manufacturer"):
            item["manufacturer"] = lookup_mac_vendor(item["mac"])
        proto = item.get("protocol", "Unknown")
        prio = protocol_priority.get(proto, 0)

        item_udp_ports = list(item.get("udp_ports") or [])
        item_confirmed_udp = list(item.get("confirmed_udp_ports") or [])
        if proto == "SSDP / UPnP":
            if 1900 not in item_udp_ports:
                item_udp_ports.append(1900)
            if 1900 not in item_confirmed_udp:
                item_confirmed_udp.append(1900)
            if item.get("port") and item["port"] not in item_udp_ports:
                item_udp_ports.append(int(item["port"]))
                item_confirmed_udp.append(int(item["port"]))
        elif proto == "mDNS / Zeroconf":
            if 5353 not in item_udp_ports:
                item_udp_ports.append(5353)
            if 5353 not in item_confirmed_udp:
                item_confirmed_udp.append(5353)

        if ip not in by_ip:
            by_ip[ip] = {
                "ip": ip,
                "name": item.get("name") or ip,
                "model": item.get("model") or "Unknown",
                "manufacturer": item.get("manufacturer") or "",
                "mac": item.get("mac") or "",
                "protocols": [proto],
                "categories": [item.get("category", "")] if item.get("category") else [],
                "ports": [item["port"]] if (item.get("port") and proto != "UDP / Nmap") else [],
                "udp_ports": sorted(set(item_udp_ports) | {5005}),
                "confirmed_udp_ports": sorted(set(item_confirmed_udp)),
                "sources": [item],
                "_best_prio": prio,
            }
            continue

        agg = by_ip[ip]
        agg["sources"].append(item)
        if proto not in agg["protocols"]:
            agg["protocols"].append(proto)

        cat = item.get("category")
        if cat and cat not in agg["categories"]:
            agg["categories"].append(cat)

        port = item.get("port")
        if port and proto != "UDP / Nmap" and port not in agg["ports"]:
            agg["ports"].append(port)

        for up in item_udp_ports:
            if up not in agg["udp_ports"]:
                agg["udp_ports"].append(up)
        for cup in item_confirmed_udp:
            if cup not in agg["confirmed_udp_ports"]:
                agg["confirmed_udp_ports"].append(cup)

        if item.get("mac") and not agg["mac"]:
            agg["mac"] = item["mac"]

        if item.get("manufacturer") and not agg["manufacturer"]:
            agg["manufacturer"] = item["manufacturer"]

        # Upgrade primary name and model if this source has higher priority or existing is generic
        is_generic_name = agg["name"].startswith(("LAN Device", "UPnP Device", "UDP Responder", "UDP Node")) or agg["name"] == ip
        if prio > agg["_best_prio"] or (is_generic_name and item.get("name")):
            if item.get("name") and not item["name"].startswith(("UDP Responder", "LAN Device")):
                agg["name"] = item["name"]
            if item.get("model") and item.get("model") != "Network Host":
                agg["model"] = item["model"]
            agg["_best_prio"] = max(agg["_best_prio"], prio)

        # Also pull open_ports from LAN scan into ports list
        open_ports = item.get("details", {}).get("open_ports", [])
        for p in open_ports:
            if p not in agg["ports"]:
                agg["ports"].append(p)

    merged = list(by_ip.values())
    for m in merged:
        m.pop("_best_prio", None)
        m["ports"].sort()
        m["udp_ports"] = sorted(set(m.get("udp_ports", [])) | {5005})
        m["confirmed_udp_ports"] = sorted(set(m.get("confirmed_udp_ports", [])))
        pkt_info = extract_device_packet_words(
            name=m.get("name", ""),
            ip=m.get("ip", ""),
            mac=m.get("mac", ""),
            vendor=m.get("manufacturer", ""),
            model=m.get("model", ""),
            protocols=m.get("protocols", []),
            udp_ports=m.get("udp_ports", []),
            confirmed_udp_ports=m.get("confirmed_udp_ports", []),
            sources=m.get("sources", []),
            arp_map=arp_map,
        )
        if pkt_info["mac"] and not m.get("mac"):
            m["mac"] = pkt_info["mac"]
        if pkt_info["vendor"] and not m.get("manufacturer"):
            m["manufacturer"] = pkt_info["vendor"]
        m["packet_words"] = pkt_info["packet_words"]
        m["spoken_packet_text"] = pkt_info["spoken_text"]
        m["short_spoken_packet_text"] = pkt_info["short_spoken_text"]

    merged.sort(key=lambda d: ip_sort_key(d.get("ip", "")))
    return merged


def run_discovery(
    methods: list[str] | None = None,
    timeout: float = 4.5,
) -> dict[str, Any]:
    """
    Run selected discovery protocols concurrently and return both merged devices
    and individual protocol records.
    """
    if not methods:
        methods = ["chromecast", "ssdp", "mdns", "arp", "udp_nmap"]

    methods_set = {m.lower() for m in methods}
    start_ts = time.time()
    local_ip, subnet = get_local_ip_and_subnet()

    tasks: dict[str, Any] = {}
    raw_results: list[dict[str, Any]] = []
    counts_by_method: dict[str, int] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        if "chromecast" in methods_set:
            tasks["chromecast"] = executor.submit(scan_chromecast, timeout)
        if "ssdp" in methods_set:
            tasks["ssdp"] = executor.submit(scan_ssdp, min(timeout, 4.0))
        if "mdns" in methods_set:
            tasks["mdns"] = executor.submit(scan_mdns, timeout)
        if "arp" in methods_set:
            tasks["arp"] = executor.submit(scan_lan_arp, min(timeout, 3.5))
        if "udp_nmap" in methods_set:
            tasks["udp_nmap"] = executor.submit(scan_udp_after_multicast, min(timeout, 4.5))

        for name, fut in tasks.items():
            try:
                items = fut.result()
                counts_by_method[name] = len(items)
                raw_results.extend(items)
            except Exception as exc:
                print(f"[{name} error] {exc}")
                counts_by_method[name] = 0

    merged = merge_devices(raw_results)
    elapsed = round(time.time() - start_ts, 2)

    return {
        "local_ip": local_ip,
        "subnet": str(subnet),
        "elapsed_seconds": elapsed,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "methods_run": list(tasks.keys()),
        "counts_by_method": counts_by_method,
        "total_unique_devices": len(merged),
        "total_raw_records": len(raw_results),
        "devices": merged,
        "raw_records": raw_results,
    }


if __name__ == "__main__":
    # Direct CLI execution runs the user's Chromecast scan snippet + summary
    devices = scan_chromecast(timeout=5.0)
    if not devices:
        print("No Chromecast devices responded on this Wi-Fi network.")
