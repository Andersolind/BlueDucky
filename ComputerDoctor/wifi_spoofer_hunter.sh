#!/usr/bin/env bash
#===============================================================================
# KALI WIFI SPOOFER HUNTER
#===============================================================================
#
# Finds hidden networks, evil twins, and WiFi spoofers using Kali tools
#
# REQUIREMENTS:
#   - Kali Linux
#   - Wireless adapter that supports monitor mode
#   - Root privileges
#
# USAGE:
#   sudo ./wifi_spoofer_hunter.sh
#   sudo ./wifi_spoofer_hunter.sh wlan0
#
#===============================================================================

set -e

# Colors
RED='\033[0;91m'
GREEN='\033[0;92m'
YELLOW='\033[0;93m'
BLUE='\033[0;94m'
MAGENTA='\033[0;95m'
CYAN='\033[0;96m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
INTERFACE="${1:-wlan0}"
MON_INTERFACE="${INTERFACE}mon"
SCAN_TIME=30
OUTPUT_DIR="/tmp/wifi_hunt_$(date +%s)"

#===============================================================================
# FUNCTIONS
#===============================================================================

print_banner() {
    echo -e "${MAGENTA}"
    echo "╔══════════════════════════════════════════════════════════════════════╗"
    echo "║                    KALI WIFI SPOOFER HUNTER                          ║"
    echo "║                   Find Hidden Networks & Spoofers                    ║"
    echo "╚══════════════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}┌─────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│ ${BOLD}$1${NC}"
    echo -e "${CYAN}└─────────────────────────────────────────────────────────────────────┘${NC}"
}

print_status() {
    echo -e "  ${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "  ${YELLOW}[!]${NC} $1"
}

print_alert() {
    echo -e "  ${RED}[⚠]${NC} ${RED}$1${NC}"
}

print_info() {
    echo -e "  ${BLUE}[i]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}This script must be run as root!${NC}"
        echo "Usage: sudo $0 [interface]"
        exit 1
    fi
}

check_tools() {
    print_section "CHECKING REQUIRED TOOLS"
    
    TOOLS=("airmon-ng" "airodump-ng" "wash" "iwlist" "iw" "macchanger")
    MISSING=()
    
    for tool in "${TOOLS[@]}"; do
        if command -v "$tool" &> /dev/null; then
            print_status "$tool found"
        else
            print_warning "$tool not found"
            MISSING+=("$tool")
        fi
    done
    
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        print_warning "Some tools missing. Install with: apt install aircrack-ng wash macchanger"
    fi
}

check_interface() {
    print_section "CHECKING WIRELESS INTERFACE"
    
    if [[ ! -d "/sys/class/net/$INTERFACE/wireless" ]]; then
        print_alert "Interface $INTERFACE is not a wireless interface!"
        echo ""
        echo "Available wireless interfaces:"
        iw dev | grep Interface | awk '{print "  " $2}'
        exit 1
    fi
    
    print_status "Interface $INTERFACE found"
    
    # Get interface info
    PHY=$(iw dev "$INTERFACE" info | grep wiphy | awk '{print "phy"$2}')
    print_info "Physical device: $PHY"
    
    # Check monitor mode support
    if iw phy "$PHY" info | grep -q "monitor"; then
        print_status "Monitor mode supported"
    else
        print_alert "Monitor mode NOT supported - some features won't work"
    fi
}

kill_interfering_processes() {
    print_section "KILLING INTERFERING PROCESSES"
    
    # Kill processes that interfere with monitor mode
    print_info "Stopping NetworkManager..."
    systemctl stop NetworkManager 2>/dev/null || true
    
    print_info "Killing wpa_supplicant..."
    killall wpa_supplicant 2>/dev/null || true
    
    print_info "Running airmon-ng check kill..."
    airmon-ng check kill 2>/dev/null || true
    
    print_status "Interfering processes killed"
}

enable_monitor_mode() {
    print_section "ENABLING MONITOR MODE"
    
    # Check if already in monitor mode
    if iwconfig "$INTERFACE" 2>/dev/null | grep -q "Mode:Monitor"; then
        print_status "$INTERFACE already in monitor mode"
        MON_INTERFACE="$INTERFACE"
        return
    fi
    
    # Try airmon-ng first
    print_info "Enabling monitor mode with airmon-ng..."
    airmon-ng start "$INTERFACE" 2>/dev/null || true
    
    # Check what interface was created
    if [[ -d "/sys/class/net/${INTERFACE}mon" ]]; then
        MON_INTERFACE="${INTERFACE}mon"
        print_status "Monitor interface: $MON_INTERFACE"
    elif [[ -d "/sys/class/net/wlan0mon" ]]; then
        MON_INTERFACE="wlan0mon"
        print_status "Monitor interface: $MON_INTERFACE"
    elif iwconfig "$INTERFACE" 2>/dev/null | grep -q "Mode:Monitor"; then
        MON_INTERFACE="$INTERFACE"
        print_status "Monitor interface: $MON_INTERFACE"
    else
        # Manual method
        print_warning "airmon-ng failed, trying manual method..."
        ip link set "$INTERFACE" down
        iw dev "$INTERFACE" set type monitor
        ip link set "$INTERFACE" up
        MON_INTERFACE="$INTERFACE"
        
        if iwconfig "$INTERFACE" 2>/dev/null | grep -q "Mode:Monitor"; then
            print_status "Monitor mode enabled manually"
        else
            print_alert "Failed to enable monitor mode!"
            exit 1
        fi
    fi
}

scan_all_networks() {
    print_section "SCANNING ALL NETWORKS (Including Hidden)"
    
    mkdir -p "$OUTPUT_DIR"
    
    print_info "Scanning for $SCAN_TIME seconds..."
    print_info "This will find:"
    print_info "  - All visible networks"
    print_info "  - Hidden networks (shown as <length: X>)"
    print_info "  - All access points and their clients"
    echo ""
    
    # Run airodump-ng in background
    timeout "$SCAN_TIME" airodump-ng "$MON_INTERFACE" \
        --write "$OUTPUT_DIR/scan" \
        --output-format csv,netxml \
        --write-interval 1 \
        2>/dev/null &
    
    AIRODUMP_PID=$!
    
    # Progress bar
    for ((i=1; i<=$SCAN_TIME; i++)); do
        PCT=$((i * 100 / SCAN_TIME))
        BAR=$(printf '%*s' $((PCT/2)) '' | tr ' ' '█')
        SPACE=$(printf '%*s' $((50 - PCT/2)) '' | tr ' ' '░')
        echo -ne "\r  Scanning: [${BAR}${SPACE}] ${PCT}% ($i/${SCAN_TIME}s)"
        sleep 1
    done
    echo ""
    
    wait $AIRODUMP_PID 2>/dev/null || true
    
    print_status "Scan complete"
}

analyze_scan_results() {
    print_section "ANALYZING SCAN RESULTS"
    
    CSV_FILE=$(ls -t "$OUTPUT_DIR"/scan-*.csv 2>/dev/null | head -1)
    
    if [[ ! -f "$CSV_FILE" ]]; then
        print_alert "No scan results found!"
        return
    fi
    
    echo ""
    echo -e "${BOLD}  ALL DETECTED ACCESS POINTS:${NC}"
    echo "  ─────────────────────────────────────────────────────────────────"
    printf "  ${BOLD}%-18s %-6s %-4s %-34s %s${NC}\n" "BSSID" "PWR" "CH" "ESSID" "ENCRYPTION"
    echo "  ─────────────────────────────────────────────────────────────────"
    
    # Parse CSV and display APs
    awk -F',' '
    /^[0-9A-Fa-f:]{17}/ && NF > 10 {
        bssid = $1
        pwr = $9
        ch = $4
        enc = $6
        essid = $14
        
        # Clean up fields
        gsub(/^ +| +$/, "", bssid)
        gsub(/^ +| +$/, "", pwr)
        gsub(/^ +| +$/, "", ch)
        gsub(/^ +| +$/, "", enc)
        gsub(/^ +| +$/, "", essid)
        
        if (length(bssid) == 17) {
            if (essid == "" || essid ~ /^[ ]*$/) {
                essid = "\033[93m<HIDDEN NETWORK>\033[0m"
            }
            printf "  %-18s %-6s %-4s %-34s %s\n", bssid, pwr, ch, essid, enc
        }
    }
    ' "$CSV_FILE" | head -30
    
    echo ""
}

find_hidden_networks() {
    print_section "HIDDEN NETWORKS DETECTED"
    
    CSV_FILE=$(ls -t "$OUTPUT_DIR"/scan-*.csv 2>/dev/null | head -1)
    
    if [[ ! -f "$CSV_FILE" ]]; then
        return
    fi
    
    # Find hidden networks (empty ESSID)
    HIDDEN=$(awk -F',' '
    /^[0-9A-Fa-f:]{17}/ && NF > 10 {
        bssid = $1
        essid = $14
        pwr = $9
        ch = $4
        
        gsub(/^ +| +$/, "", bssid)
        gsub(/^ +| +$/, "", essid)
        gsub(/^ +| +$/, "", pwr)
        gsub(/^ +| +$/, "", ch)
        
        if ((essid == "" || essid ~ /^[ ]*$/) && length(bssid) == 17) {
            print bssid "," pwr "," ch
        }
    }
    ' "$CSV_FILE")
    
    if [[ -z "$HIDDEN" ]]; then
        print_info "No hidden networks detected"
    else
        print_alert "HIDDEN NETWORKS FOUND!"
        echo ""
        printf "  ${BOLD}%-18s %-8s %-6s${NC}\n" "BSSID" "POWER" "CHANNEL"
        echo "  ────────────────────────────────────"
        
        echo "$HIDDEN" | while IFS=',' read -r bssid pwr ch; do
            printf "  %-18s %-8s %-6s\n" "$bssid" "$pwr" "$ch"
        done
        
        echo ""
        print_warning "Hidden networks can be spoofer access points!"
        print_info "To reveal hidden SSID, wait for client to connect"
        print_info "Or use: aireplay-ng -0 1 -a <BSSID> $MON_INTERFACE"
    fi
}

find_evil_twins() {
    print_section "EVIL TWIN DETECTION"
    
    CSV_FILE=$(ls -t "$OUTPUT_DIR"/scan-*.csv 2>/dev/null | head -1)
    
    if [[ ! -f "$CSV_FILE" ]]; then
        return
    fi
    
    # Group by ESSID and find duplicates
    echo ""
    
    # Find SSIDs that appear more than once
    DUPLICATES=$(awk -F',' '
    /^[0-9A-Fa-f:]{17}/ && NF > 10 {
        essid = $14
        gsub(/^ +| +$/, "", essid)
        if (essid != "" && essid !~ /^[ ]*$/) {
            count[essid]++
            data[essid] = data[essid] $1 "|" $9 "|" $4 "|" $6 "\n"
        }
    }
    END {
        for (ssid in count) {
            if (count[ssid] > 1) {
                print "SSID:" ssid
                print "COUNT:" count[ssid]
                print data[ssid]
                print "---"
            }
        }
    }
    ' "$CSV_FILE")
    
    if [[ -z "$DUPLICATES" ]]; then
        print_status "No duplicate SSIDs found (no obvious evil twins)"
    else
        print_alert "POTENTIAL EVIL TWINS DETECTED!"
        echo ""
        
        echo "$DUPLICATES" | while read -r line; do
            if [[ "$line" == SSID:* ]]; then
                SSID="${line#SSID:}"
                echo -e "  ${RED}${BOLD}Network: $SSID${NC}"
                echo "  ─────────────────────────────────────────"
                printf "  ${BOLD}%-18s %-8s %-6s %-10s${NC}\n" "BSSID" "POWER" "CH" "ENCRYPTION"
            elif [[ "$line" == COUNT:* ]]; then
                COUNT="${line#COUNT:}"
                echo -e "  ${YELLOW}Found $COUNT access points with same name!${NC}"
            elif [[ "$line" == "---" ]]; then
                echo ""
            elif [[ -n "$line" ]]; then
                IFS='|' read -r bssid pwr ch enc <<< "$line"
                if [[ -n "$bssid" ]]; then
                    printf "  %-18s %-8s %-6s %-10s\n" "$bssid" "$pwr" "$ch" "$enc"
                fi
            fi
        done
        
        echo ""
        print_warning "Multiple APs with same SSID could be:"
        print_info "  1. Evil Twin attack (rogue AP impersonating your network)"
        print_info "  2. Legitimate mesh/multiple AP setup"
        print_info "  3. Neighbor with same network name"
        echo ""
        print_info "Compare BSSIDs with your router's MAC address!"
    fi
}

find_suspicious_aps() {
    print_section "SUSPICIOUS ACCESS POINTS"
    
    CSV_FILE=$(ls -t "$OUTPUT_DIR"/scan-*.csv 2>/dev/null | head -1)
    
    if [[ ! -f "$CSV_FILE" ]]; then
        return
    fi
    
    echo ""
    print_info "Looking for suspicious characteristics..."
    echo ""
    
    # Suspicious patterns:
    # 1. Very strong signal (could be close attacker)
    # 2. Open networks (no encryption)
    # 3. Common attack names (Free WiFi, etc.)
    
    awk -F',' '
    /^[0-9A-Fa-f:]{17}/ && NF > 10 {
        bssid = $1
        pwr = $9
        ch = $4
        enc = $6
        essid = $14
        
        gsub(/^ +| +$/, "", bssid)
        gsub(/^ +| +$/, "", pwr)
        gsub(/^ +| +$/, "", ch)
        gsub(/^ +| +$/, "", enc)
        gsub(/^ +| +$/, "", essid)
        
        suspicious = 0
        reason = ""
        
        # Very strong signal
        if (pwr != "" && pwr > -30) {
            suspicious = 1
            reason = "VERY STRONG SIGNAL (attacker nearby?)"
        }
        
        # Open network
        if (enc ~ /OPN/ || enc ~ /^$/) {
            suspicious = 1
            if (reason != "") reason = reason ", "
            reason = reason "NO ENCRYPTION"
        }
        
        # Common attack SSIDs
        essid_lower = tolower(essid)
        if (essid_lower ~ /free|wifi|guest|public|open|airport|starbucks|hotel|linksys|netgear|default/) {
            if (enc ~ /OPN/) {
                suspicious = 1
                if (reason != "") reason = reason ", "
                reason = reason "COMMON HONEYPOT NAME"
            }
        }
        
        if (suspicious && length(bssid) == 17) {
            printf "  \033[91m⚠ %-18s\033[0m CH:%-3s PWR:%-4s %s\n", bssid, ch, pwr, essid
            printf "    └─ Reason: \033[93m%s\033[0m\n", reason
        }
    }
    ' "$CSV_FILE"
    
    echo ""
}

find_clients() {
    print_section "CONNECTED CLIENTS"
    
    CSV_FILE=$(ls -t "$OUTPUT_DIR"/scan-*.csv 2>/dev/null | head -1)
    
    if [[ ! -f "$CSV_FILE" ]]; then
        return
    fi
    
    echo ""
    print_info "Clients connected to access points:"
    echo ""
    printf "  ${BOLD}%-18s %-18s %-8s %s${NC}\n" "CLIENT MAC" "CONNECTED TO AP" "POWER" "PROBES"
    echo "  ─────────────────────────────────────────────────────────────────"
    
    # Parse client section of CSV (starts after second header)
    awk -F',' '
    BEGIN { in_clients = 0 }
    /Station MAC/ { in_clients = 1; next }
    in_clients && /^[0-9A-Fa-f:]{17}/ {
        client = $1
        pwr = $4
        bssid = $6
        probes = $7
        
        gsub(/^ +| +$/, "", client)
        gsub(/^ +| +$/, "", pwr)
        gsub(/^ +| +$/, "", bssid)
        gsub(/^ +| +$/, "", probes)
        
        if (length(client) == 17) {
            printf "  %-18s %-18s %-8s %s\n", client, bssid, pwr, substr(probes,1,30)
        }
    }
    ' "$CSV_FILE" | head -20
    
    echo ""
}

channel_hop_intensive_scan() {
    print_section "INTENSIVE CHANNEL-HOPPING SCAN"
    
    print_info "This scan hops through all channels to find spoofers"
    print_info "who might be hiding on unusual channels..."
    echo ""
    
    # Scan all channels including 5GHz
    for ch in 1 2 3 4 5 6 7 8 9 10 11 12 13 36 40 44 48 52 56 60 64 100 104 108 112 116 120 124 128 132 136 140 149 153 157 161 165; do
        iw dev "$MON_INTERFACE" set channel $ch 2>/dev/null && \
        echo -ne "\r  Scanning channel $ch...   " && \
        sleep 0.3
    done
    
    echo ""
    print_status "Channel scan complete"
}

capture_handshakes() {
    print_section "CAPTURE MODE (for specific target)"
    
    echo ""
    print_info "To capture handshakes from a specific network:"
    echo ""
    echo "  1. Get target BSSID and channel from scan above"
    echo "  2. Run: airodump-ng -c <CH> --bssid <BSSID> -w capture $MON_INTERFACE"
    echo "  3. In another terminal, deauth a client:"
    echo "     aireplay-ng -0 1 -a <BSSID> -c <CLIENT_MAC> $MON_INTERFACE"
    echo ""
}

reveal_hidden_ssid() {
    print_section "REVEAL HIDDEN NETWORK SSID"
    
    echo ""
    print_info "To reveal a hidden network's SSID:"
    echo ""
    echo "  Method 1: Wait for client to connect (passive)"
    echo "    airodump-ng -c <CHANNEL> --bssid <HIDDEN_BSSID> $MON_INTERFACE"
    echo ""
    echo "  Method 2: Deauth attack to force reconnection"
    echo "    aireplay-ng -0 5 -a <HIDDEN_BSSID> $MON_INTERFACE"
    echo "    (Then watch airodump-ng for SSID to appear)"
    echo ""
    echo "  Method 3: Probe request flood"
    echo "    mdk4 $MON_INTERFACE p -t <HIDDEN_BSSID>"
    echo ""
}

wps_scan() {
    print_section "WPS VULNERABILITY SCAN"
    
    if ! command -v wash &> /dev/null; then
        print_warning "wash not installed. Install with: apt install reaver"
        return
    fi
    
    print_info "Scanning for WPS-enabled access points..."
    echo ""
    
    timeout 15 wash -i "$MON_INTERFACE" 2>/dev/null | head -20
    
    echo ""
    print_info "WPS-enabled APs are vulnerable to PIN attacks"
}

restore_interface() {
    print_section "RESTORING INTERFACE"
    
    print_info "Disabling monitor mode..."
    
    airmon-ng stop "$MON_INTERFACE" 2>/dev/null || true
    
    # Manual restore if needed
    if [[ -d "/sys/class/net/$INTERFACE" ]]; then
        ip link set "$INTERFACE" down 2>/dev/null || true
        iw dev "$INTERFACE" set type managed 2>/dev/null || true
        ip link set "$INTERFACE" up 2>/dev/null || true
    fi
    
    print_info "Restarting NetworkManager..."
    systemctl start NetworkManager 2>/dev/null || true
    
    print_status "Interface restored"
}

save_report() {
    print_section "SAVING REPORT"
    
    REPORT_FILE="$OUTPUT_DIR/wifi_hunt_report.txt"
    
    {
        echo "WIFI SPOOFER HUNT REPORT"
        echo "========================"
        echo "Date: $(date)"
        echo "Interface: $INTERFACE"
        echo ""
        echo "SCAN RESULTS:"
        echo "-------------"
        cat "$OUTPUT_DIR/scan-01.csv" 2>/dev/null || echo "No CSV data"
    } > "$REPORT_FILE"
    
    print_status "Report saved to: $REPORT_FILE"
    print_info "All data saved to: $OUTPUT_DIR/"
}

cleanup() {
    print_section "CLEANUP"
    restore_interface
    echo ""
    echo -e "${GREEN}Hunt complete!${NC}"
    echo ""
    echo "Files saved to: $OUTPUT_DIR/"
    echo ""
}

#===============================================================================
# MAIN
#===============================================================================

trap cleanup EXIT

print_banner

check_root
check_tools
check_interface

echo ""
echo -e "${YELLOW}WARNING: This will disconnect you from WiFi temporarily!${NC}"
echo -e "${YELLOW}Make sure you have another way to access the internet if needed.${NC}"
echo ""
read -p "Continue? [y/N]: " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

kill_interfering_processes
enable_monitor_mode
scan_all_networks
analyze_scan_results
find_hidden_networks
find_evil_twins
find_suspicious_aps
find_clients
wps_scan
reveal_hidden_ssid
save_report

echo ""
print_section "WHAT TO DO NEXT"
echo ""
echo "  If you found suspicious networks:"
echo ""
echo "  1. Note the BSSID of suspicious APs"
echo "  2. Compare with your router's MAC address"
echo "  3. If evil twin found, the attacker is within ~100m of you"
echo "  4. Change your WiFi password immediately"
echo "  5. Consider reporting to authorities if targeted"
echo ""
echo "  Useful commands:"
echo "    - Monitor specific AP: airodump-ng -c <CH> --bssid <BSSID> $MON_INTERFACE"
echo "    - Deauth attack: aireplay-ng -0 5 -a <BSSID> $MON_INTERFACE"
echo "    - Reveal hidden: mdk4 $MON_INTERFACE p -t <BSSID>"
echo ""
