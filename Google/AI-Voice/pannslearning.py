import torch.nn as nn
from panns_inference import models

class PANNsTriangulationDetector(nn.Module):
    def __init__(self, num_classes=2):
        super(PANNsTriangulationDetector, self).__init__()
        # Load pretrained Cnn14 backbone
        # Note: In production, ensure the weights file 'Cnn14_mAP=0.431.pth' is downloaded
        self.base_model = models.Cnn14(sample_rate=48000, window_size=2048, 
                                        hop_size=512, mel_bins=64, fmin=50, 
                                        fmax=24000, classes_num=527)
        
        # Freeze the early feature extraction layers to preserve general sound patterns
        for param in self.base_model.parameters():
            param.requires_grad = False
            
        # Replace the final fully connected layer for your custom classification
        # Cnn14 uses a fc_audioset layer at the end
        in_features = self.base_model.fc_audioset.in_features
        self.base_model.fc_audioset = nn.Linear(in_features, num_classes)
        
        # Unfreeze the new layer
        for param in self.base_model.fc_audioset.parameters():
            param.requires_grad = True

    def forward(self, x):
        # PANNs models expect input shape: (batch_size, num_samples)
        output = self.base_model(x)
        return output['clipwise_output']
