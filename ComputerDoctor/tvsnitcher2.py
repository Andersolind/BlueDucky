#!/usr/bin/env python3
"""
================================================================================
REPLAY ATTACK DETECTOR WITH LEARNING & ANALYSIS
================================================================================

Enhanced detector that:
1. CLASSIFIES attacks into specific types
2. SAVES audio samples of detected attacks for analysis
3. LEARNS patterns from saved attacks to improve detection
4. PROVIDES forensic analysis tools

ATTACK TYPES DETECTED:
    - exact_replay: Identical audio played multiple times
    - near_replay: Similar audio (re-encoded/modified)
    - speaker_playback: Voice command from speaker (not live)
    - ultrasonic: Inaudible high-frequency injection
    - static_background: Recording with no natural variation
    - compression_artifacts: Audio that's been compressed/transmitted
    - synthetic_voice: AI-generated voice (TTS)

MODES:
    --detect          Normal detection mode (default)
    --analyze         Analyze saved attacks
    --learn           Learn from saved attacks to improve detection
    --playback        Play back saved attack audio
    --export          Export attack database to JSON

USAGE:
    python3 replay_detector_learning.py
    python3 replay_detector_learning.py --log attacks.json --save-audio
    python3 replay_detector_learning.py --analyze
    python3 replay_detector_learning.py --learn
    python3 replay_detector_learning.py --playback attack_001.wav

================================================================================
"""

import os
import sys
import time
import json
import wave
import struct
import subprocess
import threading
import queue
import hashlib
import sqlite3
import re
from collections import deque, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import argparse

import numpy as np

# Optional imports
HAVE_PYAUDIO = False
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "2.0.0"

# Default paths
DEFAULT_DB_PATH = os.path.expanduser("~/.replay_attacks/attacks.db")
DEFAULT_AUDIO_DIR = os.path.expanduser("~/.replay_attacks/audio")
DEFAULT_LEARNED_PATH = os.path.expanduser("~/.replay_attacks/learned_patterns.json")

# Attack type definitions
ATTACK_TYPES = {
    'exact_replay': {
        'name': 'Exact Replay',
        'description': 'Identical audio waveform detected multiple times',
        'severity': 'HIGH',
        'indicators': ['waveform_match'],
        'mitigation': 'Add liveness detection, require dynamic challenge-response'
    },
    'near_replay': {
        'name': 'Near Replay',
        'description': 'Similar audio detected (possibly re-encoded or slightly modified)',
        'severity': 'HIGH', 
        'indicators': ['perceptual_hash_match', 'spectral_similarity'],
        'mitigation': 'Implement voice biometrics, check for recording artifacts'
    },
    'speaker_playback': {
        'name': 'Speaker Playback',
        'description': 'Voice command played through speaker (not live voice)',
        'severity': 'HIGH',
        'indicators': ['no_room_reverb', 'flat_frequency_response', 'speaker_resonance'],
        'mitigation': 'Use multi-microphone arrays to detect speaker direction'
    },
    'ultrasonic': {
        'name': 'Ultrasonic Injection',
        'description': 'Inaudible high-frequency audio injection (DolphinAttack)',
        'severity': 'CRITICAL',
        'indicators': ['ultrasonic_energy', 'modulated_carrier'],
        'mitigation': 'Apply low-pass filter to microphone input, use ultrasonic jamming'
    },
    'static_background': {
        'name': 'Static Background',
        'description': 'Recording with unnaturally consistent background noise',
        'severity': 'MEDIUM',
        'indicators': ['zero_noise_variance', 'identical_noise_floor'],
        'mitigation': 'Analyze background noise patterns, require environmental variation'
    },
    'compression_artifacts': {
        'name': 'Compression Artifacts',
        'description': 'Audio shows signs of compression (MP3, AAC, etc.)',
        'severity': 'MEDIUM',
        'indicators': ['spectral_holes', 'quantization_noise', 'bandwidth_limiting'],
        'mitigation': 'Detect codec signatures, require high-quality uncompressed audio'
    },
    'synthetic_voice': {
        'name': 'Synthetic Voice',
        'description': 'AI-generated or text-to-speech audio',
        'severity': 'HIGH',
        'indicators': ['unnatural_prosody', 'missing_breath_sounds', 'perfect_timing'],
        'mitigation': 'Implement deepfake detection, analyze micro-variations'
    },
    'unknown': {
        'name': 'Unknown Attack',
        'description': 'Suspicious audio that does not match known patterns',
        'severity': 'MEDIUM',
        'indicators': [],
        'mitigation': 'Save for manual analysis, update detection rules'
    }
}

SENSITIVITY = {
    'low': {'threshold': 0.85, 'min_indicators': 3},
    'medium': {'threshold': 0.70, 'min_indicators': 2},
    'high': {'threshold': 0.50, 'min_indicators': 1}
}


# =============================================================================
# ATTACK DATABASE
# =============================================================================

class AttackDatabase:
    """SQLite database for storing and analyzing attacks"""
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                attack_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT NOT NULL,
                indicators TEXT,
                audio_file TEXT,
                audio_hash TEXT,
                sample_rate INTEGER,
                duration_ms INTEGER,
                rms_level REAL,
                peak_level REAL,
                spectral_centroid REAL,
                ultrasonic_energy REAL,
                device_events TEXT,
                notes TEXT,
                reviewed INTEGER DEFAULT 0,
                false_positive INTEGER DEFAULT 0
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attack_type TEXT NOT NULL,
                pattern_name TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                confidence_boost REAL DEFAULT 0.1,
                created_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        ''')
        
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_attacks_type ON attacks(attack_type)
        ''')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_attacks_timestamp ON attacks(timestamp)
        ''')
        
        conn.commit()
        conn.close()
    
    def save_attack(self, attack: dict) -> int:
        """Save an attack to database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO attacks (
                timestamp, attack_type, confidence, severity, indicators,
                audio_file, audio_hash, sample_rate, duration_ms,
                rms_level, peak_level, spectral_centroid, ultrasonic_energy,
                device_events, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            attack.get('timestamp', datetime.now().isoformat()),
            attack.get('attack_type', 'unknown'),
            attack.get('confidence', 0.0),
            attack.get('severity', 'MEDIUM'),
            json.dumps(attack.get('indicators', [])),
            attack.get('audio_file'),
            attack.get('audio_hash'),
            attack.get('sample_rate'),
            attack.get('duration_ms'),
            attack.get('rms_level'),
            attack.get('peak_level'),
            attack.get('spectral_centroid'),
            attack.get('ultrasonic_energy'),
            json.dumps(attack.get('device_events', [])),
            attack.get('notes')
        ))
        
        attack_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return attack_id
    
    def get_attacks(self, limit: int = 100, attack_type: str = None) -> List[dict]:
        """Get attacks from database"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if attack_type:
            c.execute('''
                SELECT * FROM attacks WHERE attack_type = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (attack_type, limit))
        else:
            c.execute('''
                SELECT * FROM attacks ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
        
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_statistics(self) -> dict:
        """Get attack statistics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        stats = {
            'total_attacks': 0,
            'by_type': {},
            'by_severity': {},
            'by_hour': {},
            'avg_confidence': 0,
            'false_positive_rate': 0
        }
        
        # Total attacks
        c.execute('SELECT COUNT(*) FROM attacks')
        stats['total_attacks'] = c.fetchone()[0]
        
        if stats['total_attacks'] == 0:
            conn.close()
            return stats
        
        # By type
        c.execute('SELECT attack_type, COUNT(*) FROM attacks GROUP BY attack_type')
        stats['by_type'] = dict(c.fetchall())
        
        # By severity
        c.execute('SELECT severity, COUNT(*) FROM attacks GROUP BY severity')
        stats['by_severity'] = dict(c.fetchall())
        
        # By hour
        c.execute('''
            SELECT strftime('%H', timestamp) as hour, COUNT(*) 
            FROM attacks GROUP BY hour ORDER BY hour
        ''')
        stats['by_hour'] = dict(c.fetchall())
        
        # Average confidence
        c.execute('SELECT AVG(confidence) FROM attacks')
        stats['avg_confidence'] = c.fetchone()[0] or 0
        
        # False positive rate
        c.execute('SELECT COUNT(*) FROM attacks WHERE false_positive = 1')
        fp_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM attacks WHERE reviewed = 1')
        reviewed_count = c.fetchone()[0]
        
        if reviewed_count > 0:
            stats['false_positive_rate'] = fp_count / reviewed_count
        
        conn.close()
        return stats
    
    def mark_false_positive(self, attack_id: int):
        """Mark an attack as false positive"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE attacks SET false_positive = 1, reviewed = 1 WHERE id = ?', (attack_id,))
        conn.commit()
        conn.close()
    
    def save_learned_pattern(self, attack_type: str, pattern_name: str, pattern_data: dict):
        """Save a learned pattern"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO learned_patterns (attack_type, pattern_name, pattern_data, created_at)
            VALUES (?, ?, ?, ?)
        ''', (attack_type, pattern_name, json.dumps(pattern_data), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_learned_patterns(self, attack_type: str = None) -> List[dict]:
        """Get learned patterns"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if attack_type:
            c.execute('SELECT * FROM learned_patterns WHERE attack_type = ?', (attack_type,))
        else:
            c.execute('SELECT * FROM learned_patterns')
        
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# =============================================================================
# AUDIO SAVER
# =============================================================================

class AudioSaver:
    """Save audio samples for analysis"""
    
    def __init__(self, audio_dir: str = DEFAULT_AUDIO_DIR, sample_rate: int = 48000):
        self.audio_dir = audio_dir
        self.sample_rate = sample_rate
        os.makedirs(audio_dir, exist_ok=True)
    
    def save(self, audio: np.ndarray, attack_type: str, attack_id: int) -> str:
        """Save audio to WAV file"""
        filename = f"attack_{attack_id:06d}_{attack_type}_{int(time.time())}.wav"
        filepath = os.path.join(self.audio_dir, filename)
        
        # Convert to 16-bit PCM
        audio_int = (audio * 32767).astype(np.int16)
        
        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int.tobytes())
        
        return filepath
    
    def load(self, filepath: str) -> Tuple[np.ndarray, int]:
        """Load audio from WAV file"""
        with wave.open(filepath, 'r') as wf:
            sample_rate = wf.getframerate()
            audio_bytes = wf.readframes(wf.getnframes())
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767
        
        return audio, sample_rate
    
    def list_files(self) -> List[str]:
        """List all saved audio files"""
        return sorted(Path(self.audio_dir).glob("attack_*.wav"))


# =============================================================================
# ATTACK CLASSIFIER
# =============================================================================

class AttackClassifier:
    """Classify attacks into specific types"""
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        
        # History for pattern matching
        self.waveform_hashes = deque(maxlen=500)
        self.spectral_hashes = deque(maxlen=200)
        self.background_profiles = deque(maxlen=100)
        
        # Learned patterns
        self.learned_patterns = {}
    
    def load_learned_patterns(self, patterns: List[dict]):
        """Load learned patterns from database"""
        for pattern in patterns:
            attack_type = pattern['attack_type']
            if attack_type not in self.learned_patterns:
                self.learned_patterns[attack_type] = []
            self.learned_patterns[attack_type].append(json.loads(pattern['pattern_data']))
    
    def classify(self, audio: np.ndarray) -> dict:
        """Classify audio and determine attack type"""
        result = {
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'severity': None,
            'indicators': [],
            'all_scores': {},
            'features': {}
        }
        
        rms = np.sqrt(np.mean(audio**2))
        if rms < 0.001:
            return result
        
        # Extract features
        features = self._extract_features(audio)
        result['features'] = features
        
        # Score each attack type
        scores = {}
        
        # Check for exact replay
        exact_score, exact_indicators = self._check_exact_replay(audio, features)
        scores['exact_replay'] = exact_score
        if exact_indicators:
            result['indicators'].extend(exact_indicators)
        
        # Check for near replay
        near_score, near_indicators = self._check_near_replay(audio, features)
        scores['near_replay'] = near_score
        if near_indicators:
            result['indicators'].extend(near_indicators)
        
        # Check for speaker playback
        speaker_score, speaker_indicators = self._check_speaker_playback(audio, features)
        scores['speaker_playback'] = speaker_score
        if speaker_indicators:
            result['indicators'].extend(speaker_indicators)
        
        # Check for ultrasonic
        ultra_score, ultra_indicators = self._check_ultrasonic(audio, features)
        scores['ultrasonic'] = ultra_score
        if ultra_indicators:
            result['indicators'].extend(ultra_indicators)
        
        # Check for static background
        static_score, static_indicators = self._check_static_background(audio, features)
        scores['static_background'] = static_score
        if static_indicators:
            result['indicators'].extend(static_indicators)
        
        # Check for compression
        comp_score, comp_indicators = self._check_compression(audio, features)
        scores['compression_artifacts'] = comp_score
        if comp_indicators:
            result['indicators'].extend(comp_indicators)
        
        # Check for synthetic voice
        synth_score, synth_indicators = self._check_synthetic_voice(audio, features)
        scores['synthetic_voice'] = synth_score
        if synth_indicators:
            result['indicators'].extend(synth_indicators)
        
        result['all_scores'] = scores
        
        # Determine primary attack type
        if scores:
            max_type = max(scores, key=scores.get)
            max_score = scores[max_type]
            
            if max_score > 0.5:
                result['is_attack'] = True
                result['attack_type'] = max_type
                result['confidence'] = max_score
                result['severity'] = ATTACK_TYPES[max_type]['severity']
        
        # Apply learned pattern boost
        if result['attack_type'] in self.learned_patterns:
            for pattern in self.learned_patterns[result['attack_type']]:
                if self._matches_pattern(features, pattern):
                    result['confidence'] = min(1.0, result['confidence'] + 0.1)
                    result['indicators'].append(f"Matches learned pattern: {pattern.get('name', 'unnamed')}")
        
        return result
    
    def _extract_features(self, audio: np.ndarray) -> dict:
        """Extract audio features for classification"""
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        features = {
            'rms': float(np.sqrt(np.mean(audio**2))),
            'peak': float(np.max(np.abs(audio))),
            'crest_factor': 0.0,
            'spectral_centroid': 0.0,
            'spectral_flatness': 0.0,
            'ultrasonic_ratio': 0.0,
            'noise_floor_variance': 0.0,
            'reverb_energy': 0.0,
            'waveform_hash': None,
            'spectral_hash': None
        }
        
        # Crest factor (peak / RMS)
        if features['rms'] > 0:
            features['crest_factor'] = features['peak'] / features['rms']
        
        # Spectral centroid
        if np.sum(fft) > 0:
            features['spectral_centroid'] = float(np.sum(freqs * fft) / np.sum(fft))
        
        # Spectral flatness
        if np.mean(fft) > 0:
            geometric_mean = np.exp(np.mean(np.log(fft + 1e-10)))
            features['spectral_flatness'] = float(geometric_mean / np.mean(fft))
        
        # Ultrasonic ratio
        ultra_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        ultra_energy = np.sum(fft[ultra_mask])
        voice_energy = np.sum(fft[voice_mask])
        if voice_energy > 0:
            features['ultrasonic_ratio'] = float(ultra_energy / voice_energy)
        
        # Noise floor variance
        segments = np.array_split(audio, 10)
        floors = [np.mean(np.sort(np.abs(s))[:len(s)//10]) for s in segments]
        features['noise_floor_variance'] = float(np.var(floors))
        
        # Reverb energy
        if len(audio) > self.sample_rate // 10:
            autocorr = np.correlate(audio[:self.sample_rate//5], audio[:self.sample_rate//5], mode='full')
            autocorr = autocorr[len(autocorr)//2:]
            if len(autocorr) > 0 and autocorr[0] > 0:
                autocorr = autocorr / autocorr[0]
                reverb_start = int(0.01 * self.sample_rate)
                reverb_end = int(0.1 * self.sample_rate)
                if reverb_end < len(autocorr):
                    features['reverb_energy'] = float(np.mean(np.abs(autocorr[reverb_start:reverb_end])))
        
        # Waveform hash
        downsampled = audio[::10]
        if np.max(np.abs(downsampled)) > 0:
            normalized = downsampled / np.max(np.abs(downsampled))
            quantized = (normalized * 100).astype(np.int8)
            features['waveform_hash'] = hashlib.md5(quantized.tobytes()).hexdigest()
        
        # Spectral hash
        spectral_bands = np.array_split(fft, 32)
        band_energies = np.array([np.sum(b) for b in spectral_bands])
        if np.max(band_energies) > 0:
            band_energies = band_energies / np.max(band_energies)
            binary_hash = (band_energies > np.median(band_energies)).astype(np.uint8)
            features['spectral_hash'] = hashlib.md5(binary_hash.tobytes()).hexdigest()
        
        return features
    
    def _check_exact_replay(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for exact waveform replay"""
        score = 0.0
        indicators = []
        
        wh = features.get('waveform_hash')
        if wh and wh in self.waveform_hashes:
            score = 1.0
            indicators.append("Exact waveform match detected")
        
        if wh:
            self.waveform_hashes.append(wh)
        
        return score, indicators
    
    def _check_near_replay(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for near replay (similar audio)"""
        score = 0.0
        indicators = []
        
        sh = features.get('spectral_hash')
        if sh:
            for old_hash in self.spectral_hashes:
                if sh == old_hash:
                    score = 0.9
                    indicators.append("Spectral fingerprint match")
                    break
            self.spectral_hashes.append(sh)
        
        return score, indicators
    
    def _check_speaker_playback(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for speaker playback characteristics"""
        score = 0.0
        indicators = []
        
        # Low reverb = speaker
        if features['reverb_energy'] < 0.02:
            score += 0.3
            indicators.append(f"No room reverb (energy: {features['reverb_energy']:.4f})")
        
        # Low crest factor = compressed speaker audio
        if features['crest_factor'] < 2.5 and features['rms'] > 0.01:
            score += 0.25
            indicators.append(f"Low dynamic range (crest: {features['crest_factor']:.2f})")
        
        # High spectral flatness = speaker (not voice)
        if features['spectral_flatness'] > 0.4:
            score += 0.2
            indicators.append(f"Flat spectrum (flatness: {features['spectral_flatness']:.2f})")
        
        return min(1.0, score), indicators
    
    def _check_ultrasonic(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for ultrasonic injection"""
        score = 0.0
        indicators = []
        
        if features['ultrasonic_ratio'] > 0.3:
            score = min(1.0, features['ultrasonic_ratio'])
            indicators.append(f"High ultrasonic energy (ratio: {features['ultrasonic_ratio']:.2f})")
        
        return score, indicators
    
    def _check_static_background(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for static background noise"""
        score = 0.0
        indicators = []
        
        # Very low noise floor variance = recording
        if features['noise_floor_variance'] < 1e-8:
            score = 0.8
            indicators.append("Zero background noise variance")
        elif features['noise_floor_variance'] < 1e-6:
            score = 0.5
            indicators.append(f"Very low noise variance ({features['noise_floor_variance']:.2e})")
        
        # Track background consistency
        self.background_profiles.append(features['noise_floor_variance'])
        
        if len(self.background_profiles) >= 5:
            recent = list(self.background_profiles)[-5:]
            if np.var(recent) < 1e-12:
                score = max(score, 0.7)
                indicators.append("Background identical across samples")
        
        return score, indicators
    
    def _check_compression(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for compression artifacts"""
        score = 0.0
        indicators = []
        
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # Check for high-frequency cutoff (MP3 signature)
        hf_mask = freqs > 16000
        total_mask = freqs > 100
        
        hf_energy = np.mean(fft[hf_mask]) if np.any(hf_mask) else 0
        total_energy = np.mean(fft[total_mask]) if np.any(total_mask) else 1
        
        if total_energy > 0:
            hf_ratio = hf_energy / total_energy
            if hf_ratio < 0.01:
                score = 0.6
                indicators.append("Sharp high-frequency cutoff (codec signature)")
        
        return score, indicators
    
    def _check_synthetic_voice(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for synthetic/TTS voice"""
        score = 0.0
        indicators = []
        
        # Synthetic voices often have very consistent timing
        # and lack micro-variations
        
        # Check for unnaturally perfect segments
        segments = np.array_split(audio, 20)
        energies = [np.sqrt(np.mean(s**2)) for s in segments]
        
        if len(energies) > 5 and np.std(energies) / (np.mean(energies) + 1e-10) < 0.05:
            score += 0.4
            indicators.append("Unnaturally consistent energy pattern")
        
        return score, indicators
    
    def _matches_pattern(self, features: dict, pattern: dict) -> bool:
        """Check if features match a learned pattern"""
        for key, value in pattern.items():
            if key in features:
                if isinstance(value, dict):
                    if 'min' in value and features[key] < value['min']:
                        return False
                    if 'max' in value and features[key] > value['max']:
                        return False
                elif features[key] != value:
                    return False
        return True


# =============================================================================
# ATTACK ANALYZER
# =============================================================================

class AttackAnalyzer:
    """Analyze saved attacks and generate insights"""
    
    def __init__(self, db: AttackDatabase, audio_saver: AudioSaver):
        self.db = db
        self.audio_saver = audio_saver
    
    def analyze_attack(self, attack_id: int) -> dict:
        """Deep analysis of a single attack"""
        attacks = self.db.get_attacks(limit=1000)
        attack = next((a for a in attacks if a['id'] == attack_id), None)
        
        if not attack:
            return {'error': f'Attack {attack_id} not found'}
        
        analysis = {
            'attack': attack,
            'type_info': ATTACK_TYPES.get(attack['attack_type'], ATTACK_TYPES['unknown']),
            'similar_attacks': [],
            'time_patterns': {},
            'recommendations': []
        }
        
        # Find similar attacks
        same_type = [a for a in attacks if a['attack_type'] == attack['attack_type'] and a['id'] != attack_id]
        analysis['similar_attacks'] = same_type[:5]
        
        # Time pattern analysis
        if same_type:
            hours = [datetime.fromisoformat(a['timestamp']).hour for a in same_type]
            hour_counts = Counter(hours)
            analysis['time_patterns'] = {
                'most_common_hour': hour_counts.most_common(1)[0] if hour_counts else None,
                'hour_distribution': dict(hour_counts)
            }
        
        # Generate recommendations
        type_info = analysis['type_info']
        analysis['recommendations'] = [
            f"Attack Type: {type_info['name']}",
            f"Severity: {type_info['severity']}",
            f"Description: {type_info['description']}",
            f"Mitigation: {type_info['mitigation']}"
        ]
        
        return analysis
    
    def generate_report(self) -> str:
        """Generate a comprehensive attack report"""
        stats = self.db.get_statistics()
        attacks = self.db.get_attacks(limit=100)
        
        report = []
        report.append("=" * 70)
        report.append("REPLAY ATTACK ANALYSIS REPORT")
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("=" * 70)
        report.append("")
        
        # Summary
        report.append("SUMMARY")
        report.append("-" * 40)
        report.append(f"Total Attacks Detected: {stats['total_attacks']}")
        report.append(f"Average Confidence: {stats['avg_confidence']:.1%}")
        if stats.get('false_positive_rate'):
            report.append(f"False Positive Rate: {stats['false_positive_rate']:.1%}")
        report.append("")
        
        # By Type
        report.append("ATTACKS BY TYPE")
        report.append("-" * 40)
        for attack_type, count in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
            type_info = ATTACK_TYPES.get(attack_type, {})
            severity = type_info.get('severity', 'UNKNOWN')
            report.append(f"  {attack_type}: {count} ({severity})")
        report.append("")
        
        # By Severity
        report.append("ATTACKS BY SEVERITY")
        report.append("-" * 40)
        for severity, count in stats['by_severity'].items():
            report.append(f"  {severity}: {count}")
        report.append("")
        
        # Time Patterns
        if stats['by_hour']:
            report.append("ATTACKS BY HOUR")
            report.append("-" * 40)
            for hour, count in sorted(stats['by_hour'].items()):
                bar = "█" * (count * 2)
                report.append(f"  {hour}:00  {bar} ({count})")
            report.append("")
        
        # Recent Attacks
        report.append("RECENT ATTACKS")
        report.append("-" * 40)
        for attack in attacks[:10]:
            ts = attack['timestamp'][:19]
            atype = attack['attack_type']
            conf = attack['confidence']
            report.append(f"  [{ts}] {atype} ({conf:.0%})")
        report.append("")
        
        # Recommendations
        report.append("RECOMMENDATIONS")
        report.append("-" * 40)
        
        if 'ultrasonic' in stats['by_type']:
            report.append("  • Implement ultrasonic filtering on microphone input")
        if 'speaker_playback' in stats['by_type']:
            report.append("  • Add liveness detection (challenge-response)")
        if 'exact_replay' in stats['by_type']:
            report.append("  • Use time-based tokens in voice commands")
        if stats['total_attacks'] > 10:
            report.append("  • Consider disabling voice assistants when not in use")
        
        report.append("")
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def learn_from_attacks(self) -> List[dict]:
        """Learn patterns from saved attacks"""
        attacks = self.db.get_attacks(limit=1000)
        learned_patterns = []
        
        # Group by type
        by_type = {}
        for attack in attacks:
            atype = attack['attack_type']
            if atype not in by_type:
                by_type[atype] = []
            by_type[atype].append(attack)
        
        # Learn patterns for each type
        for attack_type, type_attacks in by_type.items():
            if len(type_attacks) < 3:
                continue
            
            # Extract common feature ranges
            rms_values = [a['rms_level'] for a in type_attacks if a['rms_level']]
            ultra_values = [a['ultrasonic_energy'] for a in type_attacks if a['ultrasonic_energy']]
            
            pattern = {
                'name': f'auto_learned_{attack_type}_{int(time.time())}',
                'attack_type': attack_type,
                'sample_count': len(type_attacks)
            }
            
            if rms_values:
                pattern['rms_range'] = {
                    'min': float(np.percentile(rms_values, 10)),
                    'max': float(np.percentile(rms_values, 90))
                }
            
            if ultra_values:
                pattern['ultrasonic_range'] = {
                    'min': float(np.percentile(ultra_values, 10)),
                    'max': float(np.percentile(ultra_values, 90))
                }
            
            # Save to database
            self.db.save_learned_pattern(attack_type, pattern['name'], pattern)
            learned_patterns.append(pattern)
        
        return learned_patterns


# =============================================================================
# AUDIO CAPTURE
# =============================================================================

class AudioCapture:
    """Audio capture with mic verification"""
    
    SAMPLE_RATES = [48000, 44100, 32000, 22050, 16000]
    
    def __init__(self, chunk_size: int = 8192):
        self.chunk_size = chunk_size
        self.sample_rate = None
        self.audio = None
        self.stream = None
        self.queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.device_name = None
        self.mic_verified = False
        self.last_rms = 0
        self.last_audio = None
    
    def _unmute_all(self):
        """Unmute microphone"""
        for cmd in [
            ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
            ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
        ]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
        
        for control in ['Capture', 'Mic', 'Mic Boost', 'Internal Mic']:
            try:
                subprocess.run(['amixer', 'set', control, '100%', 'cap'],
                             capture_output=True, timeout=2)
            except Exception:
                pass
    
    def _verify_mic(self, stream) -> Tuple[bool, float]:
        """Verify mic is working"""
        try:
            max_rms = 0
            for _ in range(10):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                rms = np.sqrt(np.mean(audio**2))
                max_rms = max(max_rms, rms)
                time.sleep(0.05)
            return max_rms > 0.0001, max_rms
        except Exception:
            return False, 0
    
    def start(self) -> bool:
        """Start audio capture"""
        if not HAVE_PYAUDIO:
            print("  ✗ PyAudio not installed")
            return False
        
        print("  Configuring microphone...")
        self._unmute_all()
        
        try:
            p = pyaudio.PyAudio()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    for rate in self.SAMPLE_RATES:
                        try:
                            stream = p.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            is_working, rms = self._verify_mic(stream)
                            stream.close()
                            
                            if not is_working:
                                continue
                            
                            self.sample_rate = rate
                            self.device_name = info['name']
                            self.mic_verified = True
                            
                            self.audio = pyaudio.PyAudio()
                            self.stream = self.audio.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            self.running = True
                            self.thread = threading.Thread(target=self._capture, daemon=True)
                            self.thread.start()
                            
                            p.terminate()
                            print(f"  ✓ Microphone: {self.device_name[:40]} @ {rate}Hz")
                            return True
                            
                        except Exception:
                            continue
            
            p.terminate()
        except Exception as e:
            print(f"  ✗ Error: {e}")
        
        print("  ✗ No working microphone found")
        return False
    
    def _capture(self):
        """Background capture"""
        silent_count = 0
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                
                rms = np.sqrt(np.mean(audio**2))
                self.last_rms = rms
                self.last_audio = audio.copy()
                
                if rms < 0.0001:
                    silent_count += 1
                    if silent_count > 50:
                        self.mic_verified = False
                else:
                    silent_count = 0
                    self.mic_verified = True
                
                if not self.queue.full():
                    self.queue.put(audio)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self) -> Optional[np.ndarray]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def get_status(self) -> dict:
        return {
            'verified': self.mic_verified,
            'device': self.device_name,
            'sample_rate': self.sample_rate,
            'rms': self.last_rms
        }
    
    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio:
            try:
                self.audio.terminate()
            except Exception:
                pass


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class ReplayDetectorApp:
    """Main application with learning capabilities"""
    
    def __init__(self, sensitivity: str = 'medium', save_audio: bool = False,
                 db_path: str = DEFAULT_DB_PATH, audio_dir: str = DEFAULT_AUDIO_DIR):
        self.sensitivity = sensitivity
        self.save_audio = save_audio
        
        self.db = AttackDatabase(db_path)
        self.audio_saver = AudioSaver(audio_dir)
        self.audio_capture = AudioCapture()
        self.classifier = None
        self.analyzer = AttackAnalyzer(self.db, self.audio_saver)
        
        self.start_time = time.time()
        self.sample_count = 0
        self.attack_count = 0
    
    def initialize(self) -> bool:
        """Initialize detection"""
        print("=" * 70)
        print("  REPLAY ATTACK DETECTOR WITH LEARNING")
        print(f"  Version {VERSION}")
        print("=" * 70)
        print()
        print(f"  Sensitivity: {self.sensitivity.upper()}")
        print(f"  Save Audio: {'Yes' if self.save_audio else 'No'}")
        print(f"  Database: {self.db.db_path}")
        print()
        
        if not self.audio_capture.start():
            return False
        
        self.classifier = AttackClassifier(self.audio_capture.sample_rate)
        self.audio_saver.sample_rate = self.audio_capture.sample_rate
        
        # Load learned patterns
        patterns = self.db.get_learned_patterns()
        if patterns:
            self.classifier.load_learned_patterns(patterns)
            print(f"  ✓ Loaded {len(patterns)} learned patterns")
        
        # Show stats
        stats = self.db.get_statistics()
        if stats['total_attacks'] > 0:
            print(f"  ✓ Database: {stats['total_attacks']} attacks logged")
        
        print()
        return True
    
    def run_detection(self, interval: float = 0.3):
        """Run detection mode"""
        print("Starting detection...")
        print()
        time.sleep(1)
        
        try:
            while True:
                audio = self.audio_capture.get_sample()
                
                if audio is not None:
                    self.sample_count += 1
                    result = self.classifier.classify(audio)
                    
                    if result['is_attack']:
                        self.attack_count += 1
                        
                        # Build attack record
                        attack = {
                            'timestamp': datetime.now().isoformat(),
                            'attack_type': result['attack_type'],
                            'confidence': result['confidence'],
                            'severity': result['severity'],
                            'indicators': result['indicators'],
                            'rms_level': result['features'].get('rms'),
                            'peak_level': result['features'].get('peak'),
                            'spectral_centroid': result['features'].get('spectral_centroid'),
                            'ultrasonic_energy': result['features'].get('ultrasonic_ratio'),
                            'sample_rate': self.audio_capture.sample_rate,
                            'duration_ms': int(len(audio) / self.audio_capture.sample_rate * 1000)
                        }
                        
                        # Save to database
                        attack_id = self.db.save_attack(attack)
                        
                        # Save audio if enabled
                        if self.save_audio:
                            audio_file = self.audio_saver.save(audio, result['attack_type'], attack_id)
                            attack['audio_file'] = audio_file
                    
                    self._display(result)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self._shutdown()
    
    def run_analysis(self):
        """Run analysis mode"""
        report = self.analyzer.generate_report()
        print(report)
    
    def run_learn(self):
        """Run learning mode"""
        print("=" * 70)
        print("  LEARNING FROM SAVED ATTACKS")
        print("=" * 70)
        print()
        
        patterns = self.analyzer.learn_from_attacks()
        
        if patterns:
            print(f"Learned {len(patterns)} new patterns:")
            for p in patterns:
                print(f"  - {p['name']}: {p['sample_count']} samples")
        else:
            print("Not enough attacks to learn from (need at least 3 per type)")
        
        print()
    #!/usr/bin/env python3
"""
================================================================================
REPLAY ATTACK DETECTOR WITH LEARNING & ANALYSIS
================================================================================

Enhanced detector that:
1. CLASSIFIES attacks into specific types
2. SAVES audio samples of detected attacks for analysis
3. LEARNS patterns from saved attacks to improve detection
4. PROVIDES forensic analysis tools

ATTACK TYPES DETECTED:
    - exact_replay: Identical audio played multiple times
    - near_replay: Similar audio (re-encoded/modified)
    - speaker_playback: Voice command from speaker (not live)
    - ultrasonic: Inaudible high-frequency injection
    - static_background: Recording with no natural variation
    - compression_artifacts: Audio that's been compressed/transmitted
    - synthetic_voice: AI-generated voice (TTS)

MODES:
    --detect          Normal detection mode (default)
    --analyze         Analyze saved attacks
    --learn           Learn from saved attacks to improve detection
    --playback        Play back saved attack audio
    --export          Export attack database to JSON

USAGE:
    python3 replay_detector_learning.py
    python3 replay_detector_learning.py --log attacks.json --save-audio
    python3 replay_detector_learning.py --analyze
    python3 replay_detector_learning.py --learn
    python3 replay_detector_learning.py --playback attack_001.wav

================================================================================
"""

import os
import sys
import time
import json
import wave
import struct
import subprocess
import threading
import queue
import hashlib
import sqlite3
import re
from collections import deque, Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import argparse

import numpy as np

# Optional imports
HAVE_PYAUDIO = False
try:
    import pyaudio
    HAVE_PYAUDIO = True
except ImportError:
    pass


# =============================================================================
# CONFIGURATION
# =============================================================================

VERSION = "2.0.0"

# Default paths
DEFAULT_DB_PATH = os.path.expanduser("~/.replay_attacks/attacks.db")
DEFAULT_AUDIO_DIR = os.path.expanduser("~/.replay_attacks/audio")
DEFAULT_LEARNED_PATH = os.path.expanduser("~/.replay_attacks/learned_patterns.json")

# Attack type definitions
ATTACK_TYPES = {
    'exact_replay': {
        'name': 'Exact Replay',
        'description': 'Identical audio waveform detected multiple times',
        'severity': 'HIGH',
        'indicators': ['waveform_match'],
        'mitigation': 'Add liveness detection, require dynamic challenge-response'
    },
    'near_replay': {
        'name': 'Near Replay',
        'description': 'Similar audio detected (possibly re-encoded or slightly modified)',
        'severity': 'HIGH', 
        'indicators': ['perceptual_hash_match', 'spectral_similarity'],
        'mitigation': 'Implement voice biometrics, check for recording artifacts'
    },
    'speaker_playback': {
        'name': 'Speaker Playback',
        'description': 'Voice command played through speaker (not live voice)',
        'severity': 'HIGH',
        'indicators': ['no_room_reverb', 'flat_frequency_response', 'speaker_resonance'],
        'mitigation': 'Use multi-microphone arrays to detect speaker direction'
    },
    'ultrasonic': {
        'name': 'Ultrasonic Injection',
        'description': 'Inaudible high-frequency audio injection (DolphinAttack)',
        'severity': 'CRITICAL',
        'indicators': ['ultrasonic_energy', 'modulated_carrier'],
        'mitigation': 'Apply low-pass filter to microphone input, use ultrasonic jamming'
    },
    'static_background': {
        'name': 'Static Background',
        'description': 'Recording with unnaturally consistent background noise',
        'severity': 'MEDIUM',
        'indicators': ['zero_noise_variance', 'identical_noise_floor'],
        'mitigation': 'Analyze background noise patterns, require environmental variation'
    },
    'compression_artifacts': {
        'name': 'Compression Artifacts',
        'description': 'Audio shows signs of compression (MP3, AAC, etc.)',
        'severity': 'MEDIUM',
        'indicators': ['spectral_holes', 'quantization_noise', 'bandwidth_limiting'],
        'mitigation': 'Detect codec signatures, require high-quality uncompressed audio'
    },
    'synthetic_voice': {
        'name': 'Synthetic Voice',
        'description': 'AI-generated or text-to-speech audio',
        'severity': 'HIGH',
        'indicators': ['unnatural_prosody', 'missing_breath_sounds', 'perfect_timing'],
        'mitigation': 'Implement deepfake detection, analyze micro-variations'
    },
    'unknown': {
        'name': 'Unknown Attack',
        'description': 'Suspicious audio that does not match known patterns',
        'severity': 'MEDIUM',
        'indicators': [],
        'mitigation': 'Save for manual analysis, update detection rules'
    }
}

SENSITIVITY = {
    'low': {'threshold': 0.85, 'min_indicators': 3},
    'medium': {'threshold': 0.70, 'min_indicators': 2},
    'high': {'threshold': 0.50, 'min_indicators': 1}
}


# =============================================================================
# ATTACK DATABASE
# =============================================================================

class AttackDatabase:
    """SQLite database for storing and analyzing attacks"""
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                attack_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT NOT NULL,
                indicators TEXT,
                audio_file TEXT,
                audio_hash TEXT,
                sample_rate INTEGER,
                duration_ms INTEGER,
                rms_level REAL,
                peak_level REAL,
                spectral_centroid REAL,
                ultrasonic_energy REAL,
                device_events TEXT,
                notes TEXT,
                reviewed INTEGER DEFAULT 0,
                false_positive INTEGER DEFAULT 0
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS learned_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attack_type TEXT NOT NULL,
                pattern_name TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                confidence_boost REAL DEFAULT 0.1,
                created_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0
            )
        ''')
        
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_attacks_type ON attacks(attack_type)
        ''')
        c.execute('''
            CREATE INDEX IF NOT EXISTS idx_attacks_timestamp ON attacks(timestamp)
        ''')
        
        conn.commit()
        conn.close()
    
    def save_attack(self, attack: dict) -> int:
        """Save an attack to database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO attacks (
                timestamp, attack_type, confidence, severity, indicators,
                audio_file, audio_hash, sample_rate, duration_ms,
                rms_level, peak_level, spectral_centroid, ultrasonic_energy,
                device_events, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            attack.get('timestamp', datetime.now().isoformat()),
            attack.get('attack_type', 'unknown'),
            attack.get('confidence', 0.0),
            attack.get('severity', 'MEDIUM'),
            json.dumps(attack.get('indicators', [])),
            attack.get('audio_file'),
            attack.get('audio_hash'),
            attack.get('sample_rate'),
            attack.get('duration_ms'),
            attack.get('rms_level'),
            attack.get('peak_level'),
            attack.get('spectral_centroid'),
            attack.get('ultrasonic_energy'),
            json.dumps(attack.get('device_events', [])),
            attack.get('notes')
        ))
        
        attack_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return attack_id
    
    def get_attacks(self, limit: int = 100, attack_type: str = None) -> List[dict]:
        """Get attacks from database"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if attack_type:
            c.execute('''
                SELECT * FROM attacks WHERE attack_type = ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (attack_type, limit))
        else:
            c.execute('''
                SELECT * FROM attacks ORDER BY timestamp DESC LIMIT ?
            ''', (limit,))
        
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_statistics(self) -> dict:
        """Get attack statistics"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        stats = {
            'total_attacks': 0,
            'by_type': {},
            'by_severity': {},
            'by_hour': {},
            'avg_confidence': 0,
            'false_positive_rate': 0
        }
        
        # Total attacks
        c.execute('SELECT COUNT(*) FROM attacks')
        stats['total_attacks'] = c.fetchone()[0]
        
        if stats['total_attacks'] == 0:
            conn.close()
            return stats
        
        # By type
        c.execute('SELECT attack_type, COUNT(*) FROM attacks GROUP BY attack_type')
        stats['by_type'] = dict(c.fetchall())
        
        # By severity
        c.execute('SELECT severity, COUNT(*) FROM attacks GROUP BY severity')
        stats['by_severity'] = dict(c.fetchall())
        
        # By hour
        c.execute('''
            SELECT strftime('%H', timestamp) as hour, COUNT(*) 
            FROM attacks GROUP BY hour ORDER BY hour
        ''')
        stats['by_hour'] = dict(c.fetchall())
        
        # Average confidence
        c.execute('SELECT AVG(confidence) FROM attacks')
        stats['avg_confidence'] = c.fetchone()[0] or 0
        
        # False positive rate
        c.execute('SELECT COUNT(*) FROM attacks WHERE false_positive = 1')
        fp_count = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM attacks WHERE reviewed = 1')
        reviewed_count = c.fetchone()[0]
        
        if reviewed_count > 0:
            stats['false_positive_rate'] = fp_count / reviewed_count
        
        conn.close()
        return stats
    
    def mark_false_positive(self, attack_id: int):
        """Mark an attack as false positive"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE attacks SET false_positive = 1, reviewed = 1 WHERE id = ?', (attack_id,))
        conn.commit()
        conn.close()
    
    def save_learned_pattern(self, attack_type: str, pattern_name: str, pattern_data: dict):
        """Save a learned pattern"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO learned_patterns (attack_type, pattern_name, pattern_data, created_at)
            VALUES (?, ?, ?, ?)
        ''', (attack_type, pattern_name, json.dumps(pattern_data), datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
    
    def get_learned_patterns(self, attack_type: str = None) -> List[dict]:
        """Get learned patterns"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        if attack_type:
            c.execute('SELECT * FROM learned_patterns WHERE attack_type = ?', (attack_type,))
        else:
            c.execute('SELECT * FROM learned_patterns')
        
        rows = c.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# =============================================================================
# AUDIO SAVER
# =============================================================================

class AudioSaver:
    """Save audio samples for analysis"""
    
    def __init__(self, audio_dir: str = DEFAULT_AUDIO_DIR, sample_rate: int = 48000):
        self.audio_dir = audio_dir
        self.sample_rate = sample_rate
        os.makedirs(audio_dir, exist_ok=True)
    
    def save(self, audio: np.ndarray, attack_type: str, attack_id: int) -> str:
        """Save audio to WAV file"""
        filename = f"attack_{attack_id:06d}_{attack_type}_{int(time.time())}.wav"
        filepath = os.path.join(self.audio_dir, filename)
        
        # Convert to 16-bit PCM
        audio_int = (audio * 32767).astype(np.int16)
        
        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int.tobytes())
        
        return filepath
    
    def load(self, filepath: str) -> Tuple[np.ndarray, int]:
        """Load audio from WAV file"""
        with wave.open(filepath, 'r') as wf:
            sample_rate = wf.getframerate()
            audio_bytes = wf.readframes(wf.getnframes())
            audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767
        
        return audio, sample_rate
    
    def list_files(self) -> List[str]:
        """List all saved audio files"""
        return sorted(Path(self.audio_dir).glob("attack_*.wav"))


# =============================================================================
# ATTACK CLASSIFIER
# =============================================================================

class AttackClassifier:
    """Classify attacks into specific types"""
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        
        # History for pattern matching
        self.waveform_hashes = deque(maxlen=500)
        self.spectral_hashes = deque(maxlen=200)
        self.background_profiles = deque(maxlen=100)
        
        # Learned patterns
        self.learned_patterns = {}
    
    def load_learned_patterns(self, patterns: List[dict]):
        """Load learned patterns from database"""
        for pattern in patterns:
            attack_type = pattern['attack_type']
            if attack_type not in self.learned_patterns:
                self.learned_patterns[attack_type] = []
            self.learned_patterns[attack_type].append(json.loads(pattern['pattern_data']))
    
    def classify(self, audio: np.ndarray) -> dict:
        """Classify audio and determine attack type"""
        result = {
            'is_attack': False,
            'attack_type': None,
            'confidence': 0.0,
            'severity': None,
            'indicators': [],
            'all_scores': {},
            'features': {}
        }
        
        rms = np.sqrt(np.mean(audio**2))
        if rms < 0.001:
            return result
        
        # Extract features
        features = self._extract_features(audio)
        result['features'] = features
        
        # Score each attack type
        scores = {}
        
        # Check for exact replay
        exact_score, exact_indicators = self._check_exact_replay(audio, features)
        scores['exact_replay'] = exact_score
        if exact_indicators:
            result['indicators'].extend(exact_indicators)
        
        # Check for near replay
        near_score, near_indicators = self._check_near_replay(audio, features)
        scores['near_replay'] = near_score
        if near_indicators:
            result['indicators'].extend(near_indicators)
        
        # Check for speaker playback
        speaker_score, speaker_indicators = self._check_speaker_playback(audio, features)
        scores['speaker_playback'] = speaker_score
        if speaker_indicators:
            result['indicators'].extend(speaker_indicators)
        
        # Check for ultrasonic
        ultra_score, ultra_indicators = self._check_ultrasonic(audio, features)
        scores['ultrasonic'] = ultra_score
        if ultra_indicators:
            result['indicators'].extend(ultra_indicators)
        
        # Check for static background
        static_score, static_indicators = self._check_static_background(audio, features)
        scores['static_background'] = static_score
        if static_indicators:
            result['indicators'].extend(static_indicators)
        
        # Check for compression
        comp_score, comp_indicators = self._check_compression(audio, features)
        scores['compression_artifacts'] = comp_score
        if comp_indicators:
            result['indicators'].extend(comp_indicators)
        
        # Check for synthetic voice
        synth_score, synth_indicators = self._check_synthetic_voice(audio, features)
        scores['synthetic_voice'] = synth_score
        if synth_indicators:
            result['indicators'].extend(synth_indicators)
        
        result['all_scores'] = scores
        
        # Determine primary attack type
        if scores:
            max_type = max(scores, key=scores.get)
            max_score = scores[max_type]
            
            if max_score > 0.5:
                result['is_attack'] = True
                result['attack_type'] = max_type
                result['confidence'] = max_score
                result['severity'] = ATTACK_TYPES[max_type]['severity']
        
        # Apply learned pattern boost
        if result['attack_type'] in self.learned_patterns:
            for pattern in self.learned_patterns[result['attack_type']]:
                if self._matches_pattern(features, pattern):
                    result['confidence'] = min(1.0, result['confidence'] + 0.1)
                    result['indicators'].append(f"Matches learned pattern: {pattern.get('name', 'unnamed')}")
        
        return result
    
    def _extract_features(self, audio: np.ndarray) -> dict:
        """Extract audio features for classification"""
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        features = {
            'rms': float(np.sqrt(np.mean(audio**2))),
            'peak': float(np.max(np.abs(audio))),
            'crest_factor': 0.0,
            'spectral_centroid': 0.0,
            'spectral_flatness': 0.0,
            'ultrasonic_ratio': 0.0,
            'noise_floor_variance': 0.0,
            'reverb_energy': 0.0,
            'waveform_hash': None,
            'spectral_hash': None
        }
        
        # Crest factor (peak / RMS)
        if features['rms'] > 0:
            features['crest_factor'] = features['peak'] / features['rms']
        
        # Spectral centroid
        if np.sum(fft) > 0:
            features['spectral_centroid'] = float(np.sum(freqs * fft) / np.sum(fft))
        
        # Spectral flatness
        if np.mean(fft) > 0:
            geometric_mean = np.exp(np.mean(np.log(fft + 1e-10)))
            features['spectral_flatness'] = float(geometric_mean / np.mean(fft))
        
        # Ultrasonic ratio
        ultra_mask = (freqs >= 18000) & (freqs <= 22000)
        voice_mask = (freqs >= 300) & (freqs <= 3400)
        ultra_energy = np.sum(fft[ultra_mask])
        voice_energy = np.sum(fft[voice_mask])
        if voice_energy > 0:
            features['ultrasonic_ratio'] = float(ultra_energy / voice_energy)
        
        # Noise floor variance
        segments = np.array_split(audio, 10)
        floors = [np.mean(np.sort(np.abs(s))[:len(s)//10]) for s in segments]
        features['noise_floor_variance'] = float(np.var(floors))
        
        # Reverb energy
        if len(audio) > self.sample_rate // 10:
            autocorr = np.correlate(audio[:self.sample_rate//5], audio[:self.sample_rate//5], mode='full')
            autocorr = autocorr[len(autocorr)//2:]
            if len(autocorr) > 0 and autocorr[0] > 0:
                autocorr = autocorr / autocorr[0]
                reverb_start = int(0.01 * self.sample_rate)
                reverb_end = int(0.1 * self.sample_rate)
                if reverb_end < len(autocorr):
                    features['reverb_energy'] = float(np.mean(np.abs(autocorr[reverb_start:reverb_end])))
        
        # Waveform hash
        downsampled = audio[::10]
        if np.max(np.abs(downsampled)) > 0:
            normalized = downsampled / np.max(np.abs(downsampled))
            quantized = (normalized * 100).astype(np.int8)
            features['waveform_hash'] = hashlib.md5(quantized.tobytes()).hexdigest()
        
        # Spectral hash
        spectral_bands = np.array_split(fft, 32)
        band_energies = np.array([np.sum(b) for b in spectral_bands])
        if np.max(band_energies) > 0:
            band_energies = band_energies / np.max(band_energies)
            binary_hash = (band_energies > np.median(band_energies)).astype(np.uint8)
            features['spectral_hash'] = hashlib.md5(binary_hash.tobytes()).hexdigest()
        
        return features
    
    def _check_exact_replay(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for exact waveform replay"""
        score = 0.0
        indicators = []
        
        wh = features.get('waveform_hash')
        if wh and wh in self.waveform_hashes:
            score = 1.0
            indicators.append("Exact waveform match detected")
        
        if wh:
            self.waveform_hashes.append(wh)
        
        return score, indicators
    
    def _check_near_replay(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for near replay (similar audio)"""
        score = 0.0
        indicators = []
        
        sh = features.get('spectral_hash')
        if sh:
            for old_hash in self.spectral_hashes:
                if sh == old_hash:
                    score = 0.9
                    indicators.append("Spectral fingerprint match")
                    break
            self.spectral_hashes.append(sh)
        
        return score, indicators
    
    def _check_speaker_playback(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for speaker playback characteristics"""
        score = 0.0
        indicators = []
        
        # Low reverb = speaker
        if features['reverb_energy'] < 0.02:
            score += 0.3
            indicators.append(f"No room reverb (energy: {features['reverb_energy']:.4f})")
        
        # Low crest factor = compressed speaker audio
        if features['crest_factor'] < 2.5 and features['rms'] > 0.01:
            score += 0.25
            indicators.append(f"Low dynamic range (crest: {features['crest_factor']:.2f})")
        
        # High spectral flatness = speaker (not voice)
        if features['spectral_flatness'] > 0.4:
            score += 0.2
            indicators.append(f"Flat spectrum (flatness: {features['spectral_flatness']:.2f})")
        
        return min(1.0, score), indicators
    
    def _check_ultrasonic(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for ultrasonic injection"""
        score = 0.0
        indicators = []
        
        if features['ultrasonic_ratio'] > 0.3:
            score = min(1.0, features['ultrasonic_ratio'])
            indicators.append(f"High ultrasonic energy (ratio: {features['ultrasonic_ratio']:.2f})")
        
        return score, indicators
    
    def _check_static_background(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for static background noise"""
        score = 0.0
        indicators = []
        
        # Very low noise floor variance = recording
        if features['noise_floor_variance'] < 1e-8:
            score = 0.8
            indicators.append("Zero background noise variance")
        elif features['noise_floor_variance'] < 1e-6:
            score = 0.5
            indicators.append(f"Very low noise variance ({features['noise_floor_variance']:.2e})")
        
        # Track background consistency
        self.background_profiles.append(features['noise_floor_variance'])
        
        if len(self.background_profiles) >= 5:
            recent = list(self.background_profiles)[-5:]
            if np.var(recent) < 1e-12:
                score = max(score, 0.7)
                indicators.append("Background identical across samples")
        
        return score, indicators
    
    def _check_compression(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for compression artifacts"""
        score = 0.0
        indicators = []
        
        fft = np.abs(np.fft.rfft(audio))
        freqs = np.fft.rfftfreq(len(audio), 1/self.sample_rate)
        
        # Check for high-frequency cutoff (MP3 signature)
        hf_mask = freqs > 16000
        total_mask = freqs > 100
        
        hf_energy = np.mean(fft[hf_mask]) if np.any(hf_mask) else 0
        total_energy = np.mean(fft[total_mask]) if np.any(total_mask) else 1
        
        if total_energy > 0:
            hf_ratio = hf_energy / total_energy
            if hf_ratio < 0.01:
                score = 0.6
                indicators.append("Sharp high-frequency cutoff (codec signature)")
        
        return score, indicators
    
    def _check_synthetic_voice(self, audio: np.ndarray, features: dict) -> Tuple[float, List[str]]:
        """Check for synthetic/TTS voice"""
        score = 0.0
        indicators = []
        
        # Synthetic voices often have very consistent timing
        # and lack micro-variations
        
        # Check for unnaturally perfect segments
        segments = np.array_split(audio, 20)
        energies = [np.sqrt(np.mean(s**2)) for s in segments]
        
        if len(energies) > 5 and np.std(energies) / (np.mean(energies) + 1e-10) < 0.05:
            score += 0.4
            indicators.append("Unnaturally consistent energy pattern")
        
        return score, indicators
    
    def _matches_pattern(self, features: dict, pattern: dict) -> bool:
        """Check if features match a learned pattern"""
        for key, value in pattern.items():
            if key in features:
                if isinstance(value, dict):
                    if 'min' in value and features[key] < value['min']:
                        return False
                    if 'max' in value and features[key] > value['max']:
                        return False
                elif features[key] != value:
                    return False
        return True


# =============================================================================
# ATTACK ANALYZER
# =============================================================================

class AttackAnalyzer:
    """Analyze saved attacks and generate insights"""
    
    def __init__(self, db: AttackDatabase, audio_saver: AudioSaver):
        self.db = db
        self.audio_saver = audio_saver
    
    def analyze_attack(self, attack_id: int) -> dict:
        """Deep analysis of a single attack"""
        attacks = self.db.get_attacks(limit=1000)
        attack = next((a for a in attacks if a['id'] == attack_id), None)
        
        if not attack:
            return {'error': f'Attack {attack_id} not found'}
        
        analysis = {
            'attack': attack,
            'type_info': ATTACK_TYPES.get(attack['attack_type'], ATTACK_TYPES['unknown']),
            'similar_attacks': [],
            'time_patterns': {},
            'recommendations': []
        }
        
        # Find similar attacks
        same_type = [a for a in attacks if a['attack_type'] == attack['attack_type'] and a['id'] != attack_id]
        analysis['similar_attacks'] = same_type[:5]
        
        # Time pattern analysis
        if same_type:
            hours = [datetime.fromisoformat(a['timestamp']).hour for a in same_type]
            hour_counts = Counter(hours)
            analysis['time_patterns'] = {
                'most_common_hour': hour_counts.most_common(1)[0] if hour_counts else None,
                'hour_distribution': dict(hour_counts)
            }
        
        # Generate recommendations
        type_info = analysis['type_info']
        analysis['recommendations'] = [
            f"Attack Type: {type_info['name']}",
            f"Severity: {type_info['severity']}",
            f"Description: {type_info['description']}",
            f"Mitigation: {type_info['mitigation']}"
        ]
        
        return analysis
    
    def generate_report(self) -> str:
        """Generate a comprehensive attack report"""
        stats = self.db.get_statistics()
        attacks = self.db.get_attacks(limit=100)
        
        report = []
        report.append("=" * 70)
        report.append("REPLAY ATTACK ANALYSIS REPORT")
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("=" * 70)
        report.append("")
        
        # Summary
        report.append("SUMMARY")
        report.append("-" * 40)
        report.append(f"Total Attacks Detected: {stats['total_attacks']}")
        report.append(f"Average Confidence: {stats['avg_confidence']:.1%}")
        if stats.get('false_positive_rate'):
            report.append(f"False Positive Rate: {stats['false_positive_rate']:.1%}")
        report.append("")
        
        # By Type
        report.append("ATTACKS BY TYPE")
        report.append("-" * 40)
        for attack_type, count in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
            type_info = ATTACK_TYPES.get(attack_type, {})
            severity = type_info.get('severity', 'UNKNOWN')
            report.append(f"  {attack_type}: {count} ({severity})")
        report.append("")
        
        # By Severity
        report.append("ATTACKS BY SEVERITY")
        report.append("-" * 40)
        for severity, count in stats['by_severity'].items():
            report.append(f"  {severity}: {count}")
        report.append("")
        
        # Time Patterns
        if stats['by_hour']:
            report.append("ATTACKS BY HOUR")
            report.append("-" * 40)
            for hour, count in sorted(stats['by_hour'].items()):
                bar = "█" * (count * 2)
                report.append(f"  {hour}:00  {bar} ({count})")
            report.append("")
        
        # Recent Attacks
        report.append("RECENT ATTACKS")
        report.append("-" * 40)
        for attack in attacks[:10]:
            ts = attack['timestamp'][:19]
            atype = attack['attack_type']
            conf = attack['confidence']
            report.append(f"  [{ts}] {atype} ({conf:.0%})")
        report.append("")
        
        # Recommendations
        report.append("RECOMMENDATIONS")
        report.append("-" * 40)
        
        if 'ultrasonic' in stats['by_type']:
            report.append("  • Implement ultrasonic filtering on microphone input")
        if 'speaker_playback' in stats['by_type']:
            report.append("  • Add liveness detection (challenge-response)")
        if 'exact_replay' in stats['by_type']:
            report.append("  • Use time-based tokens in voice commands")
        if stats['total_attacks'] > 10:
            report.append("  • Consider disabling voice assistants when not in use")
        
        report.append("")
        report.append("=" * 70)
        
        return "\n".join(report)
    
    def learn_from_attacks(self) -> List[dict]:
        """Learn patterns from saved attacks"""
        attacks = self.db.get_attacks(limit=1000)
        learned_patterns = []
        
        # Group by type
        by_type = {}
        for attack in attacks:
            atype = attack['attack_type']
            if atype not in by_type:
                by_type[atype] = []
            by_type[atype].append(attack)
        
        # Learn patterns for each type
        for attack_type, type_attacks in by_type.items():
            if len(type_attacks) < 3:
                continue
            
            # Extract common feature ranges
            rms_values = [a['rms_level'] for a in type_attacks if a['rms_level']]
            ultra_values = [a['ultrasonic_energy'] for a in type_attacks if a['ultrasonic_energy']]
            
            pattern = {
                'name': f'auto_learned_{attack_type}_{int(time.time())}',
                'attack_type': attack_type,
                'sample_count': len(type_attacks)
            }
            
            if rms_values:
                pattern['rms_range'] = {
                    'min': float(np.percentile(rms_values, 10)),
                    'max': float(np.percentile(rms_values, 90))
                }
            
            if ultra_values:
                pattern['ultrasonic_range'] = {
                    'min': float(np.percentile(ultra_values, 10)),
                    'max': float(np.percentile(ultra_values, 90))
                }
            
            # Save to database
            self.db.save_learned_pattern(attack_type, pattern['name'], pattern)
            learned_patterns.append(pattern)
        
        return learned_patterns


# =============================================================================
# AUDIO CAPTURE
# =============================================================================

class AudioCapture:
    """Audio capture with mic verification"""
    
    SAMPLE_RATES = [48000, 44100, 32000, 22050, 16000]
    
    def __init__(self, chunk_size: int = 8192):
        self.chunk_size = chunk_size
        self.sample_rate = None
        self.audio = None
        self.stream = None
        self.queue = queue.Queue(maxsize=10)
        self.running = False
        self.thread = None
        self.device_name = None
        self.mic_verified = False
        self.last_rms = 0
        self.last_audio = None
    
    def _unmute_all(self):
        """Unmute microphone"""
        for cmd in [
            ['pactl', 'set-source-mute', '@DEFAULT_SOURCE@', '0'],
            ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', '100%'],
        ]:
            try:
                subprocess.run(cmd, capture_output=True, timeout=2)
            except Exception:
                pass
        
        for control in ['Capture', 'Mic', 'Mic Boost', 'Internal Mic']:
            try:
                subprocess.run(['amixer', 'set', control, '100%', 'cap'],
                             capture_output=True, timeout=2)
            except Exception:
                pass
    
    def _verify_mic(self, stream) -> Tuple[bool, float]:
        """Verify mic is working"""
        try:
            max_rms = 0
            for _ in range(10):
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                rms = np.sqrt(np.mean(audio**2))
                max_rms = max(max_rms, rms)
                time.sleep(0.05)
            return max_rms > 0.0001, max_rms
        except Exception:
            return False, 0
    
    def start(self) -> bool:
        """Start audio capture"""
        if not HAVE_PYAUDIO:
            print("  ✗ PyAudio not installed")
            return False
        
        print("  Configuring microphone...")
        self._unmute_all()
        
        try:
            p = pyaudio.PyAudio()
            
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                if info['maxInputChannels'] > 0:
                    for rate in self.SAMPLE_RATES:
                        try:
                            stream = p.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            is_working, rms = self._verify_mic(stream)
                            stream.close()
                            
                            if not is_working:
                                continue
                            
                            self.sample_rate = rate
                            self.device_name = info['name']
                            self.mic_verified = True
                            
                            self.audio = pyaudio.PyAudio()
                            self.stream = self.audio.open(
                                format=pyaudio.paFloat32,
                                channels=1,
                                rate=rate,
                                input=True,
                                input_device_index=i,
                                frames_per_buffer=self.chunk_size
                            )
                            
                            self.running = True
                            self.thread = threading.Thread(target=self._capture, daemon=True)
                            self.thread.start()
                            
                            p.terminate()
                            print(f"  ✓ Microphone: {self.device_name[:40]} @ {rate}Hz")
                            return True
                            
                        except Exception:
                            continue
            
            p.terminate()
        except Exception as e:
            print(f"  ✗ Error: {e}")
        
        print("  ✗ No working microphone found")
        return False
    
    def _capture(self):
        """Background capture"""
        silent_count = 0
        while self.running:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                
                rms = np.sqrt(np.mean(audio**2))
                self.last_rms = rms
                self.last_audio = audio.copy()
                
                if rms < 0.0001:
                    silent_count += 1
                    if silent_count > 50:
                        self.mic_verified = False
                else:
                    silent_count = 0
                    self.mic_verified = True
                
                if not self.queue.full():
                    self.queue.put(audio)
            except Exception:
                time.sleep(0.01)
    
    def get_sample(self) -> Optional[np.ndarray]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def get_status(self) -> dict:
        return {
            'verified': self.mic_verified,
            'device': self.device_name,
            'sample_rate': self.sample_rate,
            'rms': self.last_rms
        }
    
    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception:
                pass
        if self.audio:
            try:
                self.audio.terminate()
            except Exception:
                pass


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class ReplayDetectorApp:
    """Main application with learning capabilities"""
    
    def __init__(self, sensitivity: str = 'medium', save_audio: bool = False,
                 db_path: str = DEFAULT_DB_PATH, audio_dir: str = DEFAULT_AUDIO_DIR):
        self.sensitivity = sensitivity
        self.save_audio = save_audio
        
        self.db = AttackDatabase(db_path)
        self.audio_saver = AudioSaver(audio_dir)
        self.audio_capture = AudioCapture()
        self.classifier = None
        self.analyzer = AttackAnalyzer(self.db, self.audio_saver)
        
        self.start_time = time.time()
        self.sample_count = 0
        self.attack_count = 0
    
    def initialize(self) -> bool:
        """Initialize detection"""
        print("=" * 70)
        print("  REPLAY ATTACK DETECTOR WITH LEARNING")
        print(f"  Version {VERSION}")
        print("=" * 70)
        print()
        print(f"  Sensitivity: {self.sensitivity.upper()}")
        print(f"  Save Audio: {'Yes' if self.save_audio else 'No'}")
        print(f"  Database: {self.db.db_path}")
        print()
        
        if not self.audio_capture.start():
            return False
        
        self.classifier = AttackClassifier(self.audio_capture.sample_rate)
        self.audio_saver.sample_rate = self.audio_capture.sample_rate
        
        # Load learned patterns
        patterns = self.db.get_learned_patterns()
        if patterns:
            self.classifier.load_learned_patterns(patterns)
            print(f"  ✓ Loaded {len(patterns)} learned patterns")
        
        # Show stats
        stats = self.db.get_statistics()
        if stats['total_attacks'] > 0:
            print(f"  ✓ Database: {stats['total_attacks']} attacks logged")
        
        print()
        return True
    
    def run_detection(self, interval: float = 0.3):
        """Run detection mode"""
        print("Starting detection...")
        print()
        time.sleep(1)
        
        try:
            while True:
                audio = self.audio_capture.get_sample()
                
                if audio is not None:
                    self.sample_count += 1
                    result = self.classifier.classify(audio)
                    
                    if result['is_attack']:
                        self.attack_count += 1
                        
                        # Build attack record
                        attack = {
                            'timestamp': datetime.now().isoformat(),
                            'attack_type': result['attack_type'],
                            'confidence': result['confidence'],
                            'severity': result['severity'],
                            'indicators': result['indicators'],
                            'rms_level': result['features'].get('rms'),
                            'peak_level': result['features'].get('peak'),
                            'spectral_centroid': result['features'].get('spectral_centroid'),
                            'ultrasonic_energy': result['features'].get('ultrasonic_ratio'),
                            'sample_rate': self.audio_capture.sample_rate,
                            'duration_ms': int(len(audio) / self.audio_capture.sample_rate * 1000)
                        }
                        
                        # Save to database
                        attack_id = self.db.save_attack(attack)
                        
                        # Save audio if enabled
                        if self.save_audio:
                            audio_file = self.audio_saver.save(audio, result['attack_type'], attack_id)
                            attack['audio_file'] = audio_file
                    
                    self._display(result)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            self._shutdown()
    
    def run_analysis(self):
        """Run analysis mode"""
        report = self.analyzer.generate_report()
        print(report)
    
    def run_learn(self):
        """Run learning mode"""
        print("=" * 70)
        print("  LEARNING FROM SAVED ATTACKS")
        print("=" * 70)
        print()
        
        patterns = self.analyzer.learn_from_attacks()
        
        if patterns:
            print(f"Learned {len(patterns)} new patterns:")
            for p in patterns:
                print(f"  - {p['name']}: {p['sample_count']} samples")
        else:
            print("Not enough attacks to learn from (need at least 3 per type)")
        
        print()
    
    def _display(self, result: dict):
        """Display detection status"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 75
        runtime = int(time.time() - self.start_time)
        
        print("╔" + "═" * width + "╗")
        print("║" + " " * 18 + "REPLAY ATTACK DETECTOR" + " " * 33 + "║")
        info = f"Runtime: {runtime}s  |  Samples: {self.sample_count}  |  Attacks: {self.attack_count}"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Mic status
        mic = self.audio_capture.get_status()
        status = "✓ ACTIVE" if mic['verified'] else "⚠ SILENT"
        color = '\033[92m' if mic['verified'] else '\033[93m'
        reset = '\033[0m'
        
        print("┌─ Microphone " + "─" * (width - 14) + "┐")
        line = f"│  {color}{status}{reset}  |  Level: {mic['rms']:.4f}"
        visible = f"│  {status}  |  Level: {mic['rms']:.4f}"
        print(line + " " * (width - len(visible)) + "│")
        
        level_bars = int(min(mic['rms'] * 300, 40))
        meter = "█" * level_bars + "░" * (40 - level_bars)
        line = f"│  [{meter}]"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Detection status
        print("┌─ Attack Detection " + "─" * (width - 20) + "┐")
        
        if result['is_attack']:
            atype = result['attack_type']
            conf = result['confidence']
            severity = result['severity']
            
            sev_colors = {'CRITICAL': '\033[95m', 'HIGH': '\033[91m', 'MEDIUM': '\033[93m'}
            sev_color = sev_colors.get(severity, '')
            
            line = f"│  {sev_color}⚠ {ATTACK_TYPES[atype]['name'].upper()}{reset} ({conf:.0%})"
            visible = f"│  ⚠ {ATTACK_TYPES[atype]['name'].upper()} ({conf:.0%})"
            print(line + " " * (width - len(visible)) + "│")
            
            line = f"│  Severity: {severity}"
            print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            
            for indicator in result['indicators'][:4]:
                line = f"│  → {indicator[:width-6]}"
                print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            
            mitigation = ATTACK_TYPES[atype]['mitigation'][:width-8]
            line = f"│  Fix: {mitigation}"
            print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  ✓ No attack detected"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # All scores
        if result.get('all_scores'):
            print("┌─ Detection Scores " + "─" * (width - 20) + "┐")
            for atype, score in sorted(result['all_scores'].items(), key=lambda x: -x[1]):
                bar_len = int(score * 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                line = f"│  {atype[:20]:<20} [{bar}] {score:.0%}"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        # Stats
        stats = self.db.get_statistics()
        if stats['total_attacks'] > 0:
            print("┌─ Attack History " + "─" * (width - 18) + "┐")
            line = f"│  Total logged: {stats['total_attacks']}  |  This session: {self.attack_count}"
            print(line + " " * (width - len(line)) + "│")
            
            if stats['by_type']:
                top_type = max(stats['by_type'].items(), key=lambda x: x[1])
                line = f"│  Most common: {top_type[0]} ({top_type[1]} times)"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
        
        print("  Ctrl+C to stop  |  --analyze for report  |  --learn to improve detection")
    
    def _shutdown(self):
        """Shutdown"""
        print("\n\nShutting down...")
        self.audio_capture.stop()
        
        stats = self.db.get_statistics()
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Runtime: {int(time.time() - self.start_time)}s")
        print(f"  Samples: {self.sample_count}")
        print(f"  Attacks this session: {self.attack_count}")
        print(f"  Total in database: {stats['total_attacks']}")
        
        if self.save_audio:
            audio_files = list(self.audio_saver.list_files())
            print(f"  Saved audio files: {len(audio_files)}")
        
        print()
        print("  Run with --analyze to see full report")
        print("  Run with --learn to improve detection")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Replay Attack Detector with Learning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
    (default)    Detection mode - monitor for attacks
    --analyze    Generate analysis report from saved attacks
    --learn      Learn patterns from saved attacks
    --stats      Show quick statistics

ATTACK TYPES DETECTED:
    exact_replay         Identical audio repeated
    near_replay          Similar audio (re-encoded)
    speaker_playback     Voice from speaker (not live)
    ultrasonic           Inaudible injection
    static_background    Recording with no variation
    compression_artifacts MP3/AAC encoded audio
    synthetic_voice      AI-generated voice

EXAMPLES:
    %(prog)s                          # Start detection
    %(prog)s --save-audio             # Save attack audio samples
    %(prog)s --analyze                # View analysis report
    %(prog)s --learn                  # Learn from saved attacks
    %(prog)s --sensitivity high       # More sensitive detection
        """
    )
    
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze saved attacks and generate report')
    parser.add_argument('--learn', action='store_true',
                        help='Learn patterns from saved attacks')
    parser.add_argument('--stats', action='store_true',
                        help='Show quick statistics')
    parser.add_argument('--save-audio', action='store_true',
                        help='Save audio samples of detected attacks')
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high'],
                        default='medium')
    parser.add_argument('--db', default=DEFAULT_DB_PATH,
                        help='Database path')
    parser.add_argument('--audio-dir', default=DEFAULT_AUDIO_DIR,
                        help='Directory for saved audio')
    parser.add_argument('-i', '--interval', type=float, default=0.3)
    
    args = parser.parse_args()
    
    app = ReplayDetectorApp(
        sensitivity=args.sensitivity,
        save_audio=args.save_audio,
        db_path=args.db,
        audio_dir=args.audio_dir
    )
    
    if args.stats:
        stats = app.db.get_statistics()
        print("Attack Statistics:")
        print(f"  Total attacks: {stats['total_attacks']}")
        for atype, count in stats.get('by_type', {}).items():
            print(f"    {atype}: {count}")
        return
    
    if args.analyze:
        app.run_analysis()
        return
    
    if args.learn:
        app.run_learn()
        return
    
    # Detection mode
    if not app.initialize():
        sys.exit(1)
    
    app.run_detection(interval=args.interval)


if __name__ == "__main__":
    main()
    def _display(self, result: dict):
        """Display detection status"""
        os.system('clear' if os.name != 'nt' else 'cls')
        
        width = 75
        runtime = int(time.time() - self.start_time)
        
        print("╔" + "═" * width + "╗")
        print("║" + " " * 18 + "REPLAY ATTACK DETECTOR" + " " * 33 + "║")
        info = f"Runtime: {runtime}s  |  Samples: {self.sample_count}  |  Attacks: {self.attack_count}"
        print(f"║  {info}" + " " * (width - len(info) - 3) + "║")
        print("╚" + "═" * width + "╝")
        print()
        
        # Mic status
        mic = self.audio_capture.get_status()
        status = "✓ ACTIVE" if mic['verified'] else "⚠ SILENT"
        color = '\033[92m' if mic['verified'] else '\033[93m'
        reset = '\033[0m'
        
        print("┌─ Microphone " + "─" * (width - 14) + "┐")
        line = f"│  {color}{status}{reset}  |  Level: {mic['rms']:.4f}"
        visible = f"│  {status}  |  Level: {mic['rms']:.4f}"
        print(line + " " * (width - len(visible)) + "│")
        
        level_bars = int(min(mic['rms'] * 300, 40))
        meter = "█" * level_bars + "░" * (40 - level_bars)
        line = f"│  [{meter}]"
        print(line + " " * (width - len(line)) + "│")
        print("└" + "─" * width + "┘")
        print()
        
        # Detection status
        print("┌─ Attack Detection " + "─" * (width - 20) + "┐")
        
        if result['is_attack']:
            atype = result['attack_type']
            conf = result['confidence']
            severity = result['severity']
            
            sev_colors = {'CRITICAL': '\033[95m', 'HIGH': '\033[91m', 'MEDIUM': '\033[93m'}
            sev_color = sev_colors.get(severity, '')
            
            line = f"│  {sev_color}⚠ {ATTACK_TYPES[atype]['name'].upper()}{reset} ({conf:.0%})"
            visible = f"│  ⚠ {ATTACK_TYPES[atype]['name'].upper()} ({conf:.0%})"
            print(line + " " * (width - len(visible)) + "│")
            
            line = f"│  Severity: {severity}"
            print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            
            for indicator in result['indicators'][:4]:
                line = f"│  → {indicator[:width-6]}"
                print(line + " " * (width - len(line)) + "│")
            
            print("│" + " " * width + "│")
            
            mitigation = ATTACK_TYPES[atype]['mitigation'][:width-8]
            line = f"│  Fix: {mitigation}"
            print(line + " " * (width - len(line)) + "│")
        else:
            line = "│  ✓ No attack detected"
            print(line + " " * (width - len(line)) + "│")
        
        print("└" + "─" * width + "┘")
        print()
        
        # All scores
        if result.get('all_scores'):
            print("┌─ Detection Scores " + "─" * (width - 20) + "┐")
            for atype, score in sorted(result['all_scores'].items(), key=lambda x: -x[1]):
                bar_len = int(score * 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                line = f"│  {atype[:20]:<20} [{bar}] {score:.0%}"
                print(line + " " * (width - len(line)) + "│")
            print("└" + "─" * width + "┘")
            print()
        
        # Stats
        stats = self.db.get_statistics()
        if stats['total_attacks'] > 0:
            print("┌─ Attack History " + "─" * (width - 18) + "┐")
            line = f"│  Total logged: {stats['total_attacks']}  |  This session: {self.attack_count}"
            print(line + " " * (width - len(line)) + "│")
            
            if stats['by_type']:
                top_type = max(stats['by_type'].items(), key=lambda x: x[1])
                line = f"│  Most common: {top_type[0]} ({top_type[1]} times)"
                print(line + " " * (width - len(line)) + "│")
            
            print("└" + "─" * width + "┘")
            print()
        
        print("  Ctrl+C to stop  |  --analyze for report  |  --learn to improve detection")
    
    def _shutdown(self):
        """Shutdown"""
        print("\n\nShutting down...")
        self.audio_capture.stop()
        
        stats = self.db.get_statistics()
        print()
        print("=" * 50)
        print("  SESSION SUMMARY")
        print("=" * 50)
        print(f"  Runtime: {int(time.time() - self.start_time)}s")
        print(f"  Samples: {self.sample_count}")
        print(f"  Attacks this session: {self.attack_count}")
        print(f"  Total in database: {stats['total_attacks']}")
        
        if self.save_audio:
            audio_files = list(self.audio_saver.list_files())
            print(f"  Saved audio files: {len(audio_files)}")
        
        print()
        print("  Run with --analyze to see full report")
        print("  Run with --learn to improve detection")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Replay Attack Detector with Learning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
    (default)    Detection mode - monitor for attacks
    --analyze    Generate analysis report from saved attacks
    --learn      Learn patterns from saved attacks
    --stats      Show quick statistics

ATTACK TYPES DETECTED:
    exact_replay         Identical audio repeated
    near_replay          Similar audio (re-encoded)
    speaker_playback     Voice from speaker (not live)
    ultrasonic           Inaudible injection
    static_background    Recording with no variation
    compression_artifacts MP3/AAC encoded audio
    synthetic_voice      AI-generated voice

EXAMPLES:
    %(prog)s                          # Start detection
    %(prog)s --save-audio             # Save attack audio samples
    %(prog)s --analyze                # View analysis report
    %(prog)s --learn                  # Learn from saved attacks
    %(prog)s --sensitivity high       # More sensitive detection
        """
    )
    
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze saved attacks and generate report')
    parser.add_argument('--learn', action='store_true',
                        help='Learn patterns from saved attacks')
    parser.add_argument('--stats', action='store_true',
                        help='Show quick statistics')
    parser.add_argument('--save-audio', action='store_true',
                        help='Save audio samples of detected attacks')
    parser.add_argument('-s', '--sensitivity',
                        choices=['low', 'medium', 'high'],
                        default='medium')
    parser.add_argument('--db', default=DEFAULT_DB_PATH,
                        help='Database path')
    parser.add_argument('--audio-dir', default=DEFAULT_AUDIO_DIR,
                        help='Directory for saved audio')
    parser.add_argument('-i', '--interval', type=float, default=0.3)
    
    args = parser.parse_args()
    
    app = ReplayDetectorApp(
        sensitivity=args.sensitivity,
        save_audio=args.save_audio,
        db_path=args.db,
        audio_dir=args.audio_dir
    )
    
    if args.stats:
        stats = app.db.get_statistics()
        print("Attack Statistics:")
        print(f"  Total attacks: {stats['total_attacks']}")
        for atype, count in stats.get('by_type', {}).items():
            print(f"    {atype}: {count}")
        return
    
    if args.analyze:
        app.run_analysis()
        return
    
    if args.learn:
        app.run_learn()
        return
    
    # Detection mode
    if not app.initialize():
        sys.exit(1)
    
    app.run_detection(interval=args.interval)


if __name__ == "__main__":
    main()