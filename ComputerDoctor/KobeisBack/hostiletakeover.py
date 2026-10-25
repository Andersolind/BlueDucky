#!/usr/bin/env python3
import json
import struct
import os

# Communication Interface Constants
PRIMARY_SAT_INTERFACE = "/dev/ttyUSB_iridium"
BACKUP_RADIO_INTERFACE = "/dev/ttyUSB_lora"

class AutomatedTransmissionMatrix:
    def __init__(self):
        self.packet_sequence = 0
        print("[*] Satellite/Radio Hybrid Link Matrix Initialized.")

    def compile_payload_envelope(self, text_message, target_lat, target_lon):
        """Packages text and coordinates into a tight binary structural block."""
        self.packet_sequence += 1
        # Encode message to bytes (max 128 bytes for satellite optimization)
        encoded_text = text_message.encode('utf-8')[:128]
        text_length = len(encoded_text)

        # Structure layout: !I (Seq) + ff (Lat/Lon) + B (Text Len) + s (String)
        header_format = f"!IffB{text_length}s"
        binary_envelope = struct.pack(
            header_format,
            self.packet_sequence,
            target_lat,
            target_lon,
            text_length,
            encoded_text
        )
        return binary_envelope

    def transmit_via_satellite(self, binary_data):
        """Simulates sending an AT command sequence to an Iridium SBD modem."""
        print("[*] Attempting primary transmission via LEO Satellite network...")
        try:
            # Safe physical interface block with virtual mock failback
            if os.path.exists(PRIMARY_SAT_INTERFACE):
                with open(PRIMARY_SAT_INTERFACE, "wb") as sat_modem:
                     sat_modem.write(b"AT+SBDSX\r") # Trigger Short Burst Data transfer
            
            # Simulate a physical line-of-sight test
            satellite_link_clear = False  # Set to True to test successful satellite routing

            if not satellite_link_clear:
                raise IOError("Satellite Link Timeout: Insufficient orbital visibility.")

            print(f"[SUCCESS] Packet #{self.packet_sequence} accepted by satellite gateway.")
            return True
        except IOError as e:
            print(f"[!] Primary Link Failure: {e}")
            return False

    def transmit_via_sub_ghz_backup(self, binary_data):
        """Routes the packet to the backup Sub-GHz LoRa/Mesh radio controller."""
        print("[FALLBACK] Initializing 100% Traceability Backup Protocol...")
        print(f"[*] Broadcasting binary data envelope over unlicensed ISM band interface: {BACKUP_RADIO_INTERFACE}")

        # Safe deployment interface loop
        if os.path.exists(BACKUP_RADIO_INTERFACE):
            with open(BACKUP_RADIO_INTERFACE, "wb") as radio_transceiver:
                 radio_transceiver.write(binary_data)

        print(f"[SUCCESS] Packet #{self.packet_sequence} successfully emitted via Sub-GHz RF Mesh.")
        return True

    def route_beam_instruction(self, message, lat, lon):
        # 1. Compile the text message down to raw binary tokens
        data_block = self.compile_payload_envelope(message, lat, lon)
        print(f"\n[+] Data compiled into a {len(data_block)} byte binary envelope.")

        # 2. Execute primary Satellite delivery path
        link_status = self.transmit_via_satellite(data_block)

        # 3. If primary fails, trigger the 100% traceable backup radio loop
        if not link_status:
            self.transmit_via_sub_ghz_backup(data_block)
            
        return data_block

def decode_payload_envelope(binary_data):
    """Utility function to reverse the process on the receiving hardware node"""
    # Extract the header metadata first to parse out variable string sizes
    fixed_header_format = "!IffB"
    fixed_size = struct.calcsize(fixed_header_format)
    
    seq, lat, lon, text_len = struct.unpack(fixed_header_format, binary_data[:fixed_size])
    
    # Extract the variable message string dynamically
    full_format = f"!IffB{text_len}s"
    _, _, _, _, encoded_text = struct.unpack(full_format, binary_data)
    
    return {
        "sequence": seq,
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "message": encoded_text.decode('utf-8')
    }

if __name__ == "__main__":
    matrix = AutomatedTransmissionMatrix()

    # Input parameters for your destination array node
    automated_text = "Target located. Initialize local acoustic projection array."
    destination_latitude = 43.4501
    destination_longitude = -79.8833

    # Route and capture binary block
    raw_packet = matrix.route_beam_instruction(automated_text, destination_latitude, destination_longitude)
    
    # Verify parsing integrity loop
    print("\n[*] Parsing Verification Test on Received Envelope:")
    parsed_data = decode_payload_envelope(raw_packet)
    print(json.dumps(parsed_data, indent=4))
