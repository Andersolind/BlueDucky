import numpy as np
import pyaudio
import torch
import torch.nn as nn
import scipy.signal as signal
from transformers import HubertModel, Wav2Vec2FeatureExtractor

# ==========================================
# MODEL CONFIGURATION & HARDWARE MAP
# ==========================================
INPUT_IDX = 1   # Dodotronic/Contact Array
OUTPUT_IDX = 0  # Systems Playback Device
SR_IN = 48000
SR_OUT = 24000  # Native output rate for standard AI acoustic generators

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load extraction layers
MODEL_NAME = "facebook/hubert-base-ls960"
feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_NAME)
hubert_model = HubertModel.from_pretrained(MODEL_NAME).to(device)

# Load target profile template mapping vector
# In a full deployment, this is your extracted target speaker embedding tensor
TARGET_EMBEDDING = torch.randn(1, 256).to(device) 

class StreamingVoiceConverter(nn.Module):
    def __init__(self):
        super(StreamingVoiceConverter, self).__init__()
        # Simple projection layer representing your downstream real-time decoder
        self.decoder_layer = nn.Linear(768, 1).to(device)

    def forward(self, semantic_tokens, target_style):
        # Combines your bone-conduction semantic features with the target speaker's vocal traits
        combined = semantic_tokens + self.decoder_layer(semantic_tokens)
        return torch.tanh(combined).squeeze(-1)

# Initialize interfaces
p = pyaudio.PyAudio()
stream_in = p.open(format=pyaudio.paFloat32, channels=1, rate=SR_IN,
                    input=True, input_device_index=INPUT_IDX, frames_per_buffer=4096)
stream_out = p.open(format=pyaudio.paFloat32, channels=1, rate=SR_OUT,
                     output=True, output_device_index=OUTPUT_IDX, frames_per_buffer=2048)

converter_net = StreamingVoiceConverter()
converter_net.eval()

print("\n[*] Live Voice Conversion Streaming Loop Engaged.")
print("[*] Directing output to system headphones... Speak into the contact mic.")

try:
    while True:
        # 1. Capture streaming vibration block
        raw_in = stream_in.read(4096, exception_on_overflow=False)
        audio_chunk = np.frombuffer(raw_in, dtype=np.float32)
        
        # 2. Downsample to 16kHz for the AI model
        audio_16k = signal.resample(audio_chunk, int(len(audio_chunk) * (16000 / SR_IN)))
        
        # 3. Tokenize semantic tracking states
        inputs = feature_extractor(audio_16k, return_tensors="pt", sampling_rate=16000)
        input_values = inputs.input_values.to(device)
        
        with torch.no_grad():
            outputs = hubert_model(input_values)
            tokens = outputs.last_hidden_state
            
            # 4. Inject target voice identity mapping profiles
            synthesized_output = converter_net(tokens, TARGET_EMBEDDING)
            
            # Convert back to standard CPU data chunks
            out_frame = synthesized_output.cpu().numpy().flatten()
            
        # 5. Resample back to standard playback speed
        playback_frame = signal.resample(out_frame, int(len(out_frame) * (SR_OUT / 16000)))
        playback_frame = playback_frame / (np.max(np.abs(playback_frame)) + 1e-5)
        
        # Stream the modified voice out to your headphones
        stream_out.write(playback_frame.astype(np.float32).tobytes())

except KeyboardInterrupt:
    print("\n[*] Live streaming voice loop stopped.")
finally:
    stream_in.stop_stream(); stream_in.close()
    stream_out.stop_stream(); stream_out.close()
    p.terminate()
