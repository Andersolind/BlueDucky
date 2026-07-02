#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ultrasonic & Audio Injection Penetration Testing Toolkit
=========================================================
For authorized security testing of audio injection detection systems.

This toolkit allows you to:
1. Generate controlled ultrasonic test signals
2. Simulate replay attacks with known patterns
3. Test detection system sensitivity and accuracy
4. Validate defense mechanisms

LEGAL NOTICE: Only use on systems you own or have written authorization to test.

Hardware:
- Standard speakers (for audible range testing)
- Ultrasonic transducer (for >18kHz testing) - e.g., piezo tweeter
- Audio interface with high sample rate support (96kHz+)
"""

import numpy as np
from scipy import signal
from scipy.io import wavfile
import json
import os
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List, Tuple
import threading
import queue

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("Warning: sounddevice not available - playback disabled")


# ============================================
# TEST SIGNAL GENERATORS
# ============================================

class TestSignalGenerator:
    """
    Generates various test signals for audio injection pentesting
    """
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        
    def sine_wave(self, frequency: float, duration: float, 
                  amplitude: float = 0.8) -> np.ndarray:
        """Generate pure sine wave"""
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
    
    def sweep(self, start_freq: float, end_freq: float, 
              duration: float, amplitude: float = 0.8) -> np.ndarray:
        """Generate frequency sweep (chirp)"""
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        return (amplitude * signal.chirp(t, start_freq, duration, end_freq)).astype(np.float32)
    
    def ultrasonic_beacon(self, carrier_freq: float = 25000,
                          modulation_freq: float = 100,
                          duration: float = 5.0,
                          modulation_type: str = 'AM') -> np.ndarray:
        """
        Generate ultrasonic beacon signal (simulates cross-device tracking)
        
        Args:
            carrier_freq: Ultrasonic carrier (18000-100000 Hz)
            modulation_freq: Data modulation frequency
            duration: Signal duration
            modulation_type: 'AM', 'FM', or 'OOK' (on-off keying)
        """
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        
        # Carrier
        carrier = np.sin(2 * np.pi * carrier_freq * t)
        
        if modulation_type == 'AM':
            # Amplitude modulation
            modulator = 0.5 + 0.5 * np.sin(2 * np.pi * modulation_freq * t)
            output = carrier * modulator
            
        elif modulation_type == 'FM':
            # Frequency modulation
            deviation = 500  # Hz
            phase = 2 * np.pi * carrier_freq * t + \
                    (deviation / modulation_freq) * np.sin(2 * np.pi * modulation_freq * t)
            output = np.sin(phase)
            
        elif modulation_type == 'OOK':
            # On-off keying (common for beacons)
            symbol_duration = 1.0 / modulation_freq
            symbols = np.random.randint(0, 2, int(duration / symbol_duration))
            modulator = np.repeat(symbols, int(self.sample_rate * symbol_duration))
            modulator = modulator[:len(t)]
            output = carrier[:len(modulator)] * modulator
            
        else:
            output = carrier
        
        return (0.8 * output / np.max(np.abs(output) + 1e-10)).astype(np.float32)
    
    def simulated_voice_recording(self, duration: float = 5.0,
                                   add_recording_artifacts: bool = True) -> np.ndarray:
        """
        Generate signal that mimics a voice recording
        (for testing replay detection)
        """
        t = np.linspace(0, duration, int(self.sample_rate * duration), False)
        
        # Simulate formants (vowel-like sounds)
        formants = [
            (300, 0.3),   # F1
            (800, 0.25),  # F2
            (2500, 0.15), # F3
            (3500, 0.1),  # F4
        ]
        
        voice = np.zeros_like(t)
        for freq, amp in formants:
            # Add slight frequency wobble for realism
            wobble = 1 + 0.02 * np.sin(2 * np.pi * 5 * t)
            voice += amp * np.sin(2 * np.pi * freq * wobble * t)
        
        # Add pitch contour (fundamental frequency variation)
        f0 = 120 + 20 * np.sin(2 * np.pi * 0.5 * t)  # ~120Hz with variation
        voice *= np.sin(2 * np.pi * np.cumsum(f0) / self.sample_rate)
        
        # Add amplitude envelope (speech-like)
        envelope = np.ones_like(t)
        # Random syllable-like modulation
        syllable_rate = 4  # syllables per second
        envelope *= 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * syllable_rate * t))
        voice *= envelope
        
        if add_recording_artifacts:
            # Add recording signature artifacts
            voice = self._add_recording_artifacts(voice)
        
        return (0.8 * voice / np.max(np.abs(voice) + 1e-10)).astype(np.float32)
    
    def _add_recording_artifacts(self, audio: np.ndarray) -> np.ndarray:
        """
        Add artifacts typical of recordings (for testing "recording detection")
        """
        # 1. Consistent background noise (static)
        noise_level = 0.01
        static_noise = noise_level * np.random.randn(len(audio))
        
        # Make noise very consistent (recording signature)
        # Real recordings have frozen noise patterns
        noise_segment = static_noise[:1000]
        static_noise = np.tile(noise_segment, len(audio) // 1000 + 1)[:len(audio)]
        
        # 2. Slight compression (reduces dynamic range)
        threshold = 0.5
        ratio = 0.7
        compressed = np.where(
            np.abs(audio) > threshold,
            np.sign(audio) * (threshold + (np.abs(audio) - threshold) * ratio),
            audio
        )
        
        # 3. High-frequency rolloff (recording chain)
        nyq = self.sample_rate / 2
        cutoff = 8000 / nyq
        if cutoff < 1:
            b, a = signal.butter(2, cutoff, btype='low')
            compressed = signal.filtfilt(b, a, compressed)
        
        return compressed + static_noise
    
    def replay_attack_signal(self, original: np.ndarray, 
                             delay_ms: float = 0,
                             add_channel_effects: bool = True) -> np.ndarray:
        """
        Create a replay attack version of original audio
        
        Args:
            original: Original audio to replay
            delay_ms: Delay before replay starts
            add_channel_effects: Add speaker/room coloration
        """
        # Add delay
        delay_samples = int(delay_ms * self.sample_rate / 1000)
        delayed = np.concatenate([np.zeros(delay_samples), original])
        
        if add_channel_effects:
            # Simulate speaker frequency response (bandpass)
            nyq = self.sample_rate / 2
            low = 150 / nyq
            high = min(12000 / nyq, 0.99)
            
            if low < high:
                b, a = signal.butter(2, [low, high], btype='band')
                delayed = signal.filtfilt(b, a, delayed)
            
            # Add slight distortion (speaker nonlinearity)
            delayed = np.tanh(delayed * 1.2) / 1.2
            
            # Add room reflection (simple delay)
            reflection_delay = int(0.02 * self.sample_rate)  # 20ms
            reflection = np.concatenate([np.zeros(reflection_delay), delayed[:-reflection_delay]])
            delayed = delayed + 0.2 * reflection
        
        return (0.8 * delayed / np.max(np.abs(delayed) + 1e-10)).astype(np.float32)
    
    def injection_test_sequence(self, duration: float = 30.0) -> Tuple[np.ndarray, dict]:
        """
        Generate a comprehensive test sequence with known patterns
        
        Returns:
            audio: Test audio
            markers: Dict with timestamps of each test signal
        """
        signals = []
        markers = {'signals': []}
        current_time = 0
        
        # 1. Silence (baseline)
        silence_dur = 2.0
        signals.append(np.zeros(int(self.sample_rate * silence_dur)))
        markers['signals'].append({
            'type': 'silence',
            'start': current_time,
            'duration': silence_dur
        })
        current_time += silence_dur
        
        # 2. Reference tone (1kHz)
        tone_dur = 2.0
        signals.append(self.sine_wave(1000, tone_dur))
        markers['signals'].append({
            'type': 'reference_tone',
            'frequency': 1000,
            'start': current_time,
            'duration': tone_dur
        })
        current_time += tone_dur
        
        # 3. Simulated voice
        voice_dur = 3.0
        voice = self.simulated_voice_recording(voice_dur)
        signals.append(voice)
        markers['signals'].append({
            'type': 'simulated_voice',
            'start': current_time,
            'duration': voice_dur
        })
        current_time += voice_dur
        
        # 4. Gap
        gap_dur = 1.0
        signals.append(np.zeros(int(self.sample_rate * gap_dur)))
        current_time += gap_dur
        
        # 5. Replay of voice (should trigger detection)
        replay = self.replay_attack_signal(voice)
        signals.append(replay[:len(voice)])  # Same length
        markers['signals'].append({
            'type': 'replay_attack',
            'original_ref': 'simulated_voice',
            'start': current_time,
            'duration': voice_dur
        })
        current_time += voice_dur
        
        # 6. Near-ultrasonic sweep (18-22 kHz)
        sweep_dur = 3.0
        if self.sample_rate >= 48000:
            sweep = self.sweep(18000, 22000, sweep_dur)
            signals.append(sweep)
            markers['signals'].append({
                'type': 'ultrasonic_sweep',
                'start_freq': 18000,
                'end_freq': 22000,
                'start': current_time,
                'duration': sweep_dur
            })
            current_time += sweep_dur
        
        # 7. Ultrasonic beacon (if sample rate supports)
        if self.sample_rate >= 96000:
            beacon_dur = 3.0
            beacon = self.ultrasonic_beacon(25000, 100, beacon_dur, 'AM')
            signals.append(beacon)
            markers['signals'].append({
                'type': 'ultrasonic_beacon',
                'carrier': 25000,
                'modulation': 'AM',
                'start': current_time,
                'duration': beacon_dur
            })
            current_time += beacon_dur
        
        # 8. Another replay (testing repeated detection)
        signals.append(np.zeros(int(self.sample_rate * 1.0)))  # Gap
        current_time += 1.0
        
        signals.append(replay[:len(voice)])
        markers['signals'].append({
            'type': 'replay_attack_2',
            'original_ref': 'simulated_voice',
            'start': current_time,
            'duration': voice_dur
        })
        current_time += voice_dur
        
        # Concatenate all
        full_signal = np.concatenate(signals)
        
        # Pad to requested duration if needed
        target_samples = int(self.sample_rate * duration)
        if len(full_signal) < target_samples:
            full_signal = np.concatenate([
                full_signal, 
                np.zeros(target_samples - len(full_signal))
            ])
        
        markers['total_duration'] = len(full_signal) / self.sample_rate
        markers['sample_rate'] = self.sample_rate
        
        return full_signal.astype(np.float32), markers


# ============================================
# ULTRASONIC TRANSMITTER
# ============================================

class UltrasonicTransmitter:
    """
    Controlled ultrasonic signal transmitter for testing detection systems
    
    Requires:
    - High sample rate audio interface (96kHz or 192kHz)
    - Ultrasonic transducer/piezo tweeter connected to output
    """
    
    def __init__(self, sample_rate: int = 96000, device: int = None):
        self.sample_rate = sample_rate
        self.device = device
        self.generator = TestSignalGenerator(sample_rate)
        self.is_transmitting = False
        
        if HAS_SOUNDDEVICE:
            # Verify device supports high sample rate
            if device is not None:
                dev_info = sd.query_devices(device)
                max_sr = dev_info.get('default_samplerate', 48000)
                if max_sr < sample_rate:
                    print(f"Warning: Device max sample rate is {max_sr}, requested {sample_rate}")
    
    def transmit_test_tone(self, frequency: float = 25000, 
                           duration: float = 5.0,
                           amplitude: float = 0.8):
        """
        Transmit a single frequency test tone
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required for transmission")
            return
        
        print(f"Transmitting {frequency/1000:.1f} kHz tone for {duration}s...")
        
        tone = self.generator.sine_wave(frequency, duration, amplitude)
        sd.play(tone, self.sample_rate, device=self.device)
        sd.wait()
        
        print("Transmission complete")
    
    def transmit_beacon(self, carrier_freq: float = 25000,
                        data_rate: float = 100,
                        duration: float = 10.0,
                        modulation: str = 'AM'):
        """
        Transmit ultrasonic beacon signal
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required for transmission")
            return
        
        print(f"Transmitting beacon: {carrier_freq/1000:.1f} kHz, {modulation} modulation")
        
        beacon = self.generator.ultrasonic_beacon(
            carrier_freq, data_rate, duration, modulation
        )
        sd.play(beacon, self.sample_rate, device=self.device)
        sd.wait()
        
        print("Beacon transmission complete")
    
    def transmit_sweep(self, start_freq: float = 18000,
                       end_freq: float = 45000,
                       duration: float = 10.0):
        """
        Transmit frequency sweep through ultrasonic range
        Useful for finding transducer resonances
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required for transmission")
            return
        
        print(f"Transmitting sweep: {start_freq/1000:.1f} - {end_freq/1000:.1f} kHz")
        
        sweep = self.generator.sweep(start_freq, end_freq, duration)
        sd.play(sweep, self.sample_rate, device=self.device)
        sd.wait()
        
        print("Sweep complete")
    
    def continuous_beacon(self, carrier_freq: float = 25000,
                          interval_sec: float = 5.0,
                          burst_duration: float = 0.5):
        """
        Transmit periodic beacon bursts (simulates tracking beacon)
        Press Ctrl+C to stop
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required for transmission")
            return
        
        print(f"Starting periodic beacon: {carrier_freq/1000:.1f} kHz")
        print(f"Interval: {interval_sec}s, Burst duration: {burst_duration}s")
        print("Press Ctrl+C to stop\n")
        
        beacon = self.generator.ultrasonic_beacon(
            carrier_freq, 100, burst_duration, 'OOK'
        )
        
        self.is_transmitting = True
        burst_count = 0
        
        try:
            while self.is_transmitting:
                burst_count += 1
                print(f"Burst #{burst_count} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
                
                sd.play(beacon, self.sample_rate, device=self.device)
                sd.wait()
                
                time.sleep(interval_sec - burst_duration)
                
        except KeyboardInterrupt:
            print(f"\nStopped after {burst_count} bursts")
            self.is_transmitting = False


# ============================================
# REPLAY ATTACK SIMULATOR
# ============================================

class ReplayAttackSimulator:
    """
    Simulates replay attacks for testing detection systems
    """
    
    def __init__(self, sample_rate: int = 48000, device: int = None):
        self.sample_rate = sample_rate
        self.device = device
        self.generator = TestSignalGenerator(sample_rate)
        self.recorded_phrases = {}
    
    def record_phrase(self, name: str, duration: float = 5.0):
        """
        Record a phrase to replay later
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required")
            return
        
        print(f"Recording '{name}' for {duration}s...")
        print("Speak now!")
        
        audio = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        
        self.recorded_phrases[name] = audio.flatten()
        print(f"Recorded '{name}' ({len(audio)/self.sample_rate:.1f}s)")
    
    def replay_phrase(self, name: str, delay_sec: float = 0):
        """
        Replay a recorded phrase
        """
        if not HAS_SOUNDDEVICE:
            print("sounddevice required")
            return
        
        if name not in self.recorded_phrases:
            print(f"Phrase '{name}' not found. Record it first.")
            return
        
        if delay_sec > 0:
            print(f"Waiting {delay_sec}s before replay...")
            time.sleep(delay_sec)
        
        print(f"Replaying '{name}'...")
        
        audio = self.recorded_phrases[name]
        replay = self.generator.replay_attack_signal(audio)
        
        sd.play(replay, self.sample_rate, device=self.device)
        sd.wait()
        
        print("Replay complete")
    
    def automated_replay_attack(self, name: str, 
                                 num_replays: int = 3,
                                 interval_sec: float = 5.0):
        """
        Simulate automated replay attack with regular intervals
        """
        if name not in self.recorded_phrases:
            print(f"Phrase '{name}' not found")
            return
        
        print(f"Starting automated replay attack")
        print(f"Replays: {num_replays}, Interval: {interval_sec}s")
        print("Press Ctrl+C to stop\n")
        
        audio = self.recorded_phrases[name]
        replay = self.generator.replay_attack_signal(audio)
        
        try:
            for i in range(num_replays):
                print(f"Replay {i+1}/{num_replays} at {datetime.now().strftime('%H:%M:%S')}")
                
                sd.play(replay, self.sample_rate, device=self.device)
                sd.wait()
                
                if i < num_replays - 1:
                    time.sleep(interval_sec)
            
            print("\nAutomated replay complete")
            
        except KeyboardInterrupt:
            print(f"\nStopped after {i+1} replays")
    
    def save_phrase(self, name: str, filename: str):
        """Save recorded phrase to file"""
        if name in self.recorded_phrases:
            wavfile.write(filename, self.sample_rate, self.recorded_phrases[name])
            print(f"Saved '{name}' to {filename}")
    
    def load_phrase(self, name: str, filename: str):
        """Load phrase from file"""
        sr, audio = wavfile.read(filename)
        if sr != self.sample_rate:
            print(f"Warning: Resampling from {sr} to {self.sample_rate}")
            # Simple resampling
            ratio = self.sample_rate / sr
            audio = signal.resample(audio, int(len(audio) * ratio))
        
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32) / np.max(np.abs(audio))
        
        self.recorded_phrases[name] = audio.flatten()
        print(f"Loaded '{name}' from {filename}")


# ============================================
# PENTEST CONTROLLER
# ============================================

class AudioInjectionPentestKit:
    """
    Main controller for audio injection penetration testing
    """
    
    def __init__(self, 
                 output_device: int = None,
                 standard_sample_rate: int = 48000,
                 ultrasonic_sample_rate: int = 96000):
        
        self.output_device = output_device
        self.standard_sr = standard_sample_rate
        self.ultrasonic_sr = ultrasonic_sample_rate
        
        # Initialize components
        self.generator = TestSignalGenerator(standard_sample_rate)
        self.ultrasonic_tx = UltrasonicTransmitter(ultrasonic_sample_rate, output_device)
        self.replay_sim = ReplayAttackSimulator(standard_sample_rate, output_device)
        
        # Test log
        self.test_log = []
    
    def run_detection_test(self, save_signals: bool = True) -> dict:
        """
        Run comprehensive detection system test
        Returns test report
        """
        print("\n" + "=" * 60)
        print("AUDIO INJECTION DETECTION TEST")
        print("=" * 60)
        print("\nThis will transmit test signals to verify your detection system.")
        print("Ensure your detection system is running and monitoring.\n")
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'tests': []
        }
        
        # Test 1: Audible reference tone
        print("[Test 1/6] Reference tone (1kHz)...")
        input("Press Enter to transmit...")
        self._log_test('reference_tone', '1kHz sine wave')
        tone = self.generator.sine_wave(1000, 3.0)
        if HAS_SOUNDDEVICE:
            sd.play(tone, self.standard_sr, device=self.output_device)
            sd.wait()
        report['tests'].append({'name': 'reference_tone', 'frequency': 1000})
        print("✓ Complete. Did your detector see this?\n")
        time.sleep(2)
        
        # Test 2: Simulated voice recording
        print("[Test 2/6] Simulated voice (with recording artifacts)...")
        input("Press Enter to transmit...")
        self._log_test('simulated_voice', 'Voice-like signal with recording signatures')
        voice = self.generator.simulated_voice_recording(4.0, add_recording_artifacts=True)
        if save_signals:
            wavfile.write('/tmp/test_voice.wav', self.standard_sr, voice)
        if HAS_SOUNDDEVICE:
            sd.play(voice, self.standard_sr, device=self.output_device)
            sd.wait()
        report['tests'].append({'name': 'simulated_voice', 'artifacts': True})
        print("✓ Complete. Should trigger 'recording detected'.\n")
        time.sleep(2)
        
        # Test 3: Replay of voice
        print("[Test 3/6] Replay attack (same voice signal)...")
        input("Press Enter to transmit...")
        self._log_test('replay_attack', 'Replay of previous voice signal')
        replay = self.generator.replay_attack_signal(voice)
        if HAS_SOUNDDEVICE:
            sd.play(replay, self.standard_sr, device=self.output_device)
            sd.wait()
        report['tests'].append({'name': 'replay_attack', 'delay_from_original': 'immediate'})
        print("✓ Complete. Should trigger 'replay detected' + 'waveform repetition'.\n")
        time.sleep(2)
        
        # Test 4: Second replay (testing repeated detection)
        print("[Test 4/6] Second replay attack...")
        input("Press Enter to transmit...")
        self._log_test('replay_attack_2', 'Second replay of same signal')
        if HAS_SOUNDDEVICE:
            sd.play(replay, self.standard_sr, device=self.output_device)
            sd.wait()
        report['tests'].append({'name': 'replay_attack_2'})
        print("✓ Complete. Should trigger another replay detection.\n")
        time.sleep(2)
        
        # Test 5: Near-ultrasonic sweep
        print("[Test 5/6] Near-ultrasonic sweep (18-22 kHz)...")
        input("Press Enter to transmit...")
        self._log_test('ultrasonic_sweep', '18-22kHz frequency sweep')
        sweep = self.generator.sweep(18000, 22000, 5.0)
        if save_signals:
            wavfile.write('/tmp/test_sweep.wav', self.standard_sr, sweep)
        if HAS_SOUNDDEVICE:
            sd.play(sweep, self.standard_sr, device=self.output_device)
            sd.wait()
        report['tests'].append({'name': 'ultrasonic_sweep', 'range': '18-22kHz'})
        print("✓ Complete. Ultramic should detect this.\n")
        time.sleep(2)
        
        # Test 6: Ultrasonic beacon (if high sample rate available)
        print("[Test 6/6] Ultrasonic beacon (25kHz AM)...")
        if self.ultrasonic_sr >= 96000:
            input("Press Enter to transmit (requires ultrasonic transducer)...")
            self._log_test('ultrasonic_beacon', '25kHz AM-modulated beacon')
            beacon = TestSignalGenerator(self.ultrasonic_sr).ultrasonic_beacon(
                25000, 100, 5.0, 'AM'
            )
            if save_signals:
                wavfile.write('/tmp/test_beacon.wav', self.ultrasonic_sr, beacon)
            if HAS_SOUNDDEVICE:
                sd.play(beacon, self.ultrasonic_sr, device=self.output_device)
                sd.wait()
            report['tests'].append({'name': 'ultrasonic_beacon', 'carrier': 25000})
            print("✓ Complete. Should trigger ultrasonic detection.\n")
        else:
            print("⚠ Skipped - requires 96kHz+ sample rate\n")
            report['tests'].append({'name': 'ultrasonic_beacon', 'skipped': True})
        
        # Summary
        print("=" * 60)
        print("TEST SEQUENCE COMPLETE")
        print("=" * 60)
        print("\nExpected detections:")
        print("  • Test 1: Signal presence")
        print("  • Test 2: Recording signatures (static noise, too clean)")
        print("  • Test 3: Replay attack (waveform repetition)")
        print("  • Test 4: Second replay detection")
        print("  • Test 5: Ultrasonic activity")
        print("  • Test 6: Ultrasonic beacon")
        print("\nCheck your detection system logs to verify.\n")
        
        # Save report
        report_file = '/tmp/pentest_report.json'
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Test report saved to: {report_file}")
        
        return report
    
    def _log_test(self, name: str, description: str):
        """Log test execution"""
        self.test_log.append({
            'timestamp': datetime.now().isoformat(),
            'test': name,
            'description': description
        })
    
    def generate_test_files(self, output_dir: str = '/tmp/pentest_signals'):
        """
        Generate test signal files for offline testing
        """
        os.makedirs(output_dir, exist_ok=True)
        
        print(f"Generating test signals in {output_dir}/\n")
        
        # Standard rate signals
        gen = TestSignalGenerator(self.standard_sr)
        
        signals = {
            'reference_1khz.wav': gen.sine_wave(1000, 5.0),
            'voice_clean.wav': gen.simulated_voice_recording(5.0, False),
            'voice_recording.wav': gen.simulated_voice_recording(5.0, True),
            'sweep_100_8000.wav': gen.sweep(100, 8000, 5.0),
            'sweep_18000_22000.wav': gen.sweep(18000, 22000, 5.0),
        }
        
        # Add replay version
        voice = signals['voice_recording.wav']
        signals['voice_replay.wav'] = gen.replay_attack_signal(voice)
        
        # High sample rate signals
        if self.ultrasonic_sr >= 96000:
            gen_ultra = TestSignalGenerator(self.ultrasonic_sr)
            signals['beacon_25khz_am.wav'] = (
                gen_ultra.ultrasonic_beacon(25000, 100, 5.0, 'AM'),
                self.ultrasonic_sr
            )
            signals['beacon_25khz_ook.wav'] = (
                gen_ultra.ultrasonic_beacon(25000, 50, 5.0, 'OOK'),
                self.ultrasonic_sr
            )
            signals['sweep_20000_40000.wav'] = (
                gen_ultra.sweep(20000, 40000, 5.0),
                self.ultrasonic_sr
            )
        
        # Save all
        for filename, data in signals.items():
            filepath = os.path.join(output_dir, filename)
            if isinstance(data, tuple):
                audio, sr = data
            else:
                audio, sr = data, self.standard_sr
            
            wavfile.write(filepath, sr, audio)
            print(f"  ✓ {filename}")
        
        # Generate test sequence
        seq, markers = gen.injection_test_sequence(60.0)
        wavfile.write(os.path.join(output_dir, 'full_test_sequence.wav'), self.standard_sr, seq)
        with open(os.path.join(output_dir, 'test_sequence_markers.json'), 'w') as f:
            json.dump(markers, f, indent=2)
        print(f"  ✓ full_test_sequence.wav (with markers)")
        
        print(f"\nGenerated {len(signals) + 1} test files")
        print(f"Use these to test your detection system offline")


def list_audio_devices():
    """List available audio output devices"""
    if not HAS_SOUNDDEVICE:
        print("sounddevice not available")
        return
    
    print("\nAvailable Audio OUTPUT Devices:")
    print("=" * 60)
    for i, dev in enumerate(sd.query_devices()):
        if dev['max_output_channels'] > 0:
            sr = dev['default_samplerate']
            print(f"[{i}] {dev['name']}")
            print(f"    Sample Rate: {sr} Hz | Channels: {dev['max_output_channels']}")


def interactive_mode():
    """Interactive pentest menu"""
    print("\n" + "=" * 60)
    print("AUDIO INJECTION PENTEST TOOLKIT")
    print("=" * 60)
    
    list_audio_devices()
    
    device = input("\nEnter output device ID (or Enter for default): ").strip()
    device = int(device) if device else None
    
    kit = AudioInjectionPentestKit(output_device=device)
    
    while True:
        print("\n--- MENU ---")
        print("1. Run detection test sequence")
        print("2. Generate test signal files")
        print("3. Ultrasonic beacon (continuous)")
        print("4. Replay attack simulator")
        print("5. Single test tone")
        print("6. Frequency sweep")
        print("0. Exit")
        
        choice = input("\nSelect option: ").strip()
        
        if choice == '1':
            kit.run_detection_test()
            
        elif choice == '2':
            kit.generate_test_files()
            
        elif choice == '3':
            freq = input("Carrier frequency kHz (default 25): ").strip()
            freq = float(freq) * 1000 if freq else 25000
            interval = input("Interval seconds (default 5): ").strip()
            interval = float(interval) if interval else 5.0
            kit.ultrasonic_tx.continuous_beacon(freq, interval)
            
        elif choice == '4':
            print("\n--- REPLAY SIMULATOR ---")
            print("a. Record new phrase")
            print("b. Replay phrase")
            print("c. Automated replay attack")
            sub = input("Select: ").strip()
            
            if sub == 'a':
                name = input("Phrase name: ").strip()
                dur = input("Duration seconds (default 5): ").strip()
                dur = float(dur) if dur else 5.0
                kit.replay_sim.record_phrase(name, dur)
            elif sub == 'b':
                name = input("Phrase name to replay: ").strip()
                kit.replay_sim.replay_phrase(name)
            elif sub == 'c':
                name = input("Phrase name: ").strip()
                num = input("Number of replays (default 3): ").strip()
                num = int(num) if num else 3
                kit.replay_sim.automated_replay_attack(name, num)
                
        elif choice == '5':
            freq = input("Frequency Hz (default 1000): ").strip()
            freq = float(freq) if freq else 1000
            dur = input("Duration seconds (default 3): ").strip()
            dur = float(dur) if dur else 3.0
            tone = kit.generator.sine_wave(freq, dur)
            if HAS_SOUNDDEVICE:
                sd.play(tone, kit.standard_sr, device=device)
                sd.wait()
                
        elif choice == '6':
            start = input("Start frequency Hz (default 100): ").strip()
            start = float(start) if start else 100
            end = input("End frequency Hz (default 20000): ").strip()
            end = float(end) if end else 20000
            dur = input("Duration seconds (default 10): ").strip()
            dur = float(dur) if dur else 10.0
            sweep = kit.generator.sweep(start, end, dur)
            if HAS_SOUNDDEVICE:
                sd.play(sweep, kit.standard_sr, device=device)
                sd.wait()
                
        elif choice == '0':
            print("Exiting...")
            break


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Audio Injection Penetration Testing Toolkit'
    )
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Run in interactive mode')
    parser.add_argument('--test', '-t', action='store_true',
                        help='Run detection test sequence')
    parser.add_argument('--generate', '-g', action='store_true',
                        help='Generate test signal files')
    parser.add_argument('--device', '-d', type=int,
                        help='Audio output device ID')
    parser.add_argument('--list-devices', action='store_true',
                        help='List audio devices')
    parser.add_argument('--beacon', type=float,
                        help='Transmit continuous beacon at specified kHz')
    parser.add_argument('--output-dir', default='/tmp/pentest_signals',
                        help='Output directory for generated files')
    
    args = parser.parse_args()
    
    if args.list_devices:
        list_audio_devices()
        exit(0)
    
    if args.interactive:
        interactive_mode()
    elif args.test:
        kit = AudioInjectionPentestKit(output_device=args.device)
        kit.run_detection_test()
    elif args.generate:
        kit = AudioInjectionPentestKit(output_device=args.device)
        kit.generate_test_files(args.output_dir)
    elif args.beacon:
        tx = UltrasonicTransmitter(96000, args.device)
        tx.continuous_beacon(args.beacon * 1000)
    else:
        # Default: show help
        parser.print_help()
        print("\n\nQuick start:")
        print("  python3 pentest_toolkit.py --interactive")
        print("  python3 pentest_toolkit.py --test")
        print("  python3 pentest_toolkit.py --generate")