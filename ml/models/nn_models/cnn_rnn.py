from dataclasses import dataclass

import torch
from torch import nn

from ml.models.nn_models.nn_utils import get_param_size
from ml.models.nn_models.rnn import RNNClassifier, supported_rnns
from ml.utils.nn_config import NNModelConfig


@dataclass
class CNNRNNConfig(NNModelConfig):
    pass


class DeepSpeech(RNNClassifier):
    def __init__(self, conv, input_size, out_time_feature, batch_size, rnn_type=nn.LSTM, labels="abc", eeg_conf=None,
                 rnn_hidden_size=768, n_layers=5, bidirectional=True, is_inference_softmax=True, output_size=2):
        super(DeepSpeech, self).__init__(batch_size, input_size=input_size, out_time_feature=out_time_feature,
                                         rnn_type=rnn_type, rnn_hidden_size=rnn_hidden_size, n_layers=n_layers,
                                         bidirectional=bidirectional, is_inference_softmax=is_inference_softmax,
                                         output_size=output_size, batch_norm_size=input_size)

        self.hidden_size = rnn_hidden_size
        self.hidden_layers = n_layers
        self.rnn_type = rnn_type
        self.labels = labels
        self.bidirectional = bidirectional

        self.conv = conv
        print(f'Number of parameters\tconv: {get_param_size(self.conv)}\trnn: {get_param_size(super())}')

    def forward(self, x):
        if len(x.size()) <= 2:
            x = torch.unsqueeze(x, dim=1)

        x = self.conv(x.to(torch.float))    # batch x channel x time x freq

        if len(x.size()) == 4:      # batch x channel x time_feature x freq_feature
            # Collapse feature dimension   batch x feature x time
            x = x.transpose(2, 3)
            sizes = x.size()
            x = x.reshape(sizes[0], sizes[1] * sizes[2], sizes[3])

        x = super().forward(x)
        return x


def construct_cnn_rnn(cfg, construct_cnn_func, output_size, device):
    conv, conv_out_ftrs = construct_cnn_func(cfg, use_as_extractor=True)
    input_size = conv_out_ftrs['n_channels'] * conv_out_ftrs['width']
    return DeepSpeech(conv.to(device), input_size, out_time_feature=conv_out_ftrs['height'], batch_size=cfg['batch_size'],
                      rnn_type=supported_rnns[cfg['rnn_type']], labels="abc", eeg_conf=None,
                      rnn_hidden_size=cfg['rnn_hidden_size'], n_layers=cfg['rnn_n_layers'],
                      bidirectional=cfg['bidirectional'], output_size=output_size,
                      is_inference_softmax=cfg.get('is_inference_softmax', True))
