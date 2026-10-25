#!/usr/bin/env python3
import sys, argparse, time
from PyQt5 import QtCore, QtWidgets, QtGui
import sip
from sdr_backend import SDRScannerEngine  

class CalibratingSDRDashboard(QtWidgets.QWidget):
    def __init__(self, selected_freq):
        QtWidgets.QWidget.__init__(self)
        
        self.setWindowTitle("Self-Calibrating SDR Scanner & Transcription Panel")
        self.resize(1280, 1000)
        self.main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(self.main_layout)

        # 1. CRITICAL OVER-STIMULATION ALERT BANNER
        self.alert_banner = QtWidgets.QLabel("ENVIRONMENT MATRIX NORMAL: NO OVER-STIMULATION PULSES DETECTED")
        self.alert_banner.setStyleSheet("font-size: 14px; color: #00ff00; background-color: #0b0c10; padding: 8px; font-weight: bold; border: 2px solid #00ff00;")
        self.alert_banner.setAlignment(QtCore.Qt.AlignCenter)
        self.main_layout.addWidget(self.alert_banner)

        # 2. Top Banner Status Label
        self.scan_label = QtWidgets.QLabel("CALIBRATING CORE BACKGROUND ENVIRONMENT FLOOR... STAND BY")
        self.scan_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffcc00; margin-top: 5px;")
        self.main_layout.addWidget(self.scan_label)

        # 3. Operational Mode Help Banner
        self.mode_help_label = QtWidgets.QLabel("PRESS [SPACEBAR] TO ENGAGE/RELEASE HARD LOCK LISTEN MODE ON CURRENT TARGET")
        self.mode_help_label.setStyleSheet("font-size: 12px; color: #ffffff; background-color: #333333; padding: 4px; font-weight: bold;")
        self.mode_help_label.setAlignment(QtCore.Qt.AlignCenter)
        self.main_layout.addWidget(self.mode_help_label)

        # Initialize core orchestrator engine
        self.engine = SDRScannerEngine(
            start_freq=selected_freq,
            ui_callback=self.update_status_label,
            text_callback=self.update_transcription_box,
            bpm_callback=self.update_rhythm_chart,
            alert_callback=self.trigger_critical_overstimulation_alert # Connect threat vector
        )

        self.rf_widget = sip.wrapinstance(self.engine.qtgui_freq_sink.qwidget(), QtWidgets.QWidget)
        self.audio_widget = sip.wrapinstance(self.engine.audio_sink_waterfall.qwidget(), QtWidgets.QWidget)
        self.main_layout.addWidget(self.rf_widget)
        self.main_layout.addWidget(self.audio_widget)

        # 4. Middle Layout Splitter: Rhythm Timeline vs Distance Profile Tracker
        self.dashboard_grid = QtWidgets.QHBoxLayout()
        self.main_layout.addLayout(self.dashboard_grid)

        # Left Column: Rhythm Pacing Graph Panel
        self.rhythm_display = QtWidgets.QTextEdit()
        self.rhythm_display.setReadOnly(True)
        self.rhythm_display.setMaximumHeight(140)
        self.rhythm_display.setStyleSheet("background-color: #0b0c10; color: #66fcf1; font-family: monospace; font-size: 11px;")
        self.dashboard_grid.addWidget(self.rhythm_display)

        # Right Column: NEW Calculated Distance History Chart Panel
        self.distance_display = QtWidgets.QTextEdit()
        self.distance_display.setReadOnly(True)
        self.distance_display.setMaximumHeight(140)
        self.distance_display.setStyleSheet("background-color: #0b0c10; color: #ff00ff; font-family: monospace; font-size: 11px;")
        self.dashboard_grid.addWidget(self.distance_display)
        self.distance_display.append("[Perimeter Distance History Timeline Initialized - Monitoring 2-5m Loop Vectors]")

        # 5. Bottom UI Component: Whisper Output Panel
        self.text_display = QtWidgets.QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFontPointSize(14)
        self.main_layout.addWidget(self.text_display)

        self.engine.start()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Space:
            if self.engine.toggle_manual_listen():
                self.mode_help_label.setText("!!! [LOCKED] MANUAL LISTEN OVERRIDE ENGAGED !!!")
                self.mode_help_label.setStyleSheet("font-size: 12px; color: #ffffff; background-color: #ff0000; padding: 4px; font-weight: bold;")
            else:
                self.mode_help_label.setText("PRESS [SPACEBAR] TO ENGAGE/RELEASE HARD LOCK LISTEN MODE ON CURRENT TARGET")
                self.mode_help_label.setStyleSheet("font-size: 12px; color: #ffffff; background-color: #333333; padding: 4px; font-weight: bold;")
                # Clean the critical alert banner display back to green when resuming sweeps
                self.alert_banner.setText("ENVIRONMENT MATRIX NORMAL: NO OVER-STIMULATION PULSES DETECTED")
                self.alert_banner.setStyleSheet("font-size: 14px; color: #00ff00; background-color: #0b0c10; padding: 8px; font-weight: bold; border: 2px solid #00ff00;")
        else:
            super().keyPressEvent(event)

    def trigger_critical_overstimulation_alert(self, freq_mhz, distance_m, bpm, rms_val):
        """Cross-connected alert radar thread. Instantly flashes scarlet when high-power loops lock."""
        timestamp = time.strftime('%H:%M:%S')
        alert_text = f"⚠️ [CRITICAL OVER-STIMULATION SPIKE AT {timestamp}] | STN ON: {freq_mhz:.4f} MHz | DISTANCE: {distance_m:.2f}m | PULSE: {bpm:.1f} BPM"
        
        # Force the GUI window layer to re-render in warning colors immediately
        QtCore.QMetaObject.invokeMethod(
            self.alert_banner, "setText", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, alert_text)
        )
        QtCore.QMetaObject.invokeMethod(
            self.alert_banner, "setStyleSheet", QtCore.Qt.QueuedConnection, 
            QtCore.Q_ARG(str, "font-size: 14px; color: #ffffff; background-color: #ff0000; padding: 8px; font-weight: bold; border: 3px solid #ffffff; animate: flash;")
        )

    def update_status_label(self, message_text):
        QtCore.QMetaObject.invokeMethod(self.scan_label, "setText", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, message_text))

    def update_transcription_box(self, phrase_text):
        QtCore.QMetaObject.invokeMethod(self.text_display, "append", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, phrase_text))

    def update_rhythm_chart(self, bpm_value):
        chart_line = f"[{time.strftime('%H:%M:%S')}] {bpm_value:6.1f} BPM : {'█' * min(int(bpm_value / 3), 40)}"
        QtCore.QMetaObject.invokeMethod(self.rhythm_display, "append", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(str, chart_line))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Adaptive Squelch Frontend.")
    parser.add_argument("--freq", type=str, choices=["13", "27"], required=True)
    args = parser.parse_args()
    
    freq_map = {"13": 13.56e6, "27": 27.12e6}
    qapp = QtWidgets.QApplication(sys.argv)
    dashboard = CalibratingSDRDashboard(selected_freq=freq_map[args.freq])
    dashboard.show()
    sys.exit(qapp.exec_())
