import os
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from ml.models.train_managers.train_manager import BaseTrainManager
from tqdm import tqdm

from ml.models.nn_models.bonn_rnn import BonnRNN
from ml.models.nn_models.cnns_on_chb_mit import CHBMITCNN


class KerasTrainManager(BaseTrainManager):
    def __init__(self, class_labels, cfg, dataloaders, metrics):
        super(KerasTrainManager, self).__init__(class_labels, cfg, dataloaders, metrics)
        os.environ["CUDA_VISIBLE_DEVICES"] = "0"
        Path(self.cfg['model_path']).parent.mkdir(exist_ok=True, parents=True)

    def _init_model(self):
        if self.cfg['reproduce'] == 'chbmit-cnn':
            return CHBMITCNN(self.cfg['model_path'], self.cfg)
        elif self.cfg['reproduce'] == 'bonn-rnn':
            return BonnRNN(self.cfg['model_path'], self.cfg)

    def _init_device(self):
        if self.cfg['cuda']:
            os.environ["CUDA_VISIBLE_DEVICES"] = '0'

    def _update_by_epoch(self, phase, epoch):
        for metric in self.metrics[phase]:
            best_flag = metric.average_meter.update_best()
            if metric.save_model and best_flag and phase == 'val':
                print("Found better validated model, saving to %s" % self.cfg['model_path'])
                self.model.save_model()

            # reset epoch average meter
            metric.average_meter.reset()

        if phase == 'val':
            print(f'epoch {epoch} ended.')

    def _predict(self, phase):
        batch_size = self.cfg['batch_size']

        self.check_keys_from_dict([phase], self.dataloaders)

        dtype_ = np.int if self.cfg['task_type'] == 'classify' else np.float
        # ラベルが入れられなかった部分を除くため、小さな負の数を初期値として格納
        pred_list = np.zeros((len(self.dataloaders[phase]) * batch_size, 1), dtype=dtype_) - 1000000
        label_list = np.zeros((len(self.dataloaders[phase]) * batch_size, 1), dtype=dtype_) - 1000000
        for i, (inputs, labels) in tqdm(enumerate(self.dataloaders[phase]), total=len(self.dataloaders[phase])):

            labels = labels.numpy().reshape(-1,)
            preds = self.model.predict(inputs.numpy())

            pred_list[i * batch_size:i * batch_size + preds.shape[0], 0] = preds.reshape(-1,)
            label_list[i * batch_size:i * batch_size + labels.shape[0], 0] = labels

        # postprocessing:
        pred_list, label_list = pred_list[~(pred_list == -1000000)], label_list[~(label_list == -1000000)]
        n = 10
        k = 6

        label_list = label_list[n:]
        preds = np.zeros(pred_list.shape[0])
        preds[(pd.Series(pred_list).rolling(window=n).sum() >= k).values] = 1
        preds = preds[n:]
        return preds, label_list

    def train(self, model=None):
        if model:
            self.model = model

        self.check_keys_from_dict(['train', 'val'], self.dataloaders)

        for epoch in range(self.cfg['epochs']):
            for phase in ['train', 'val']:
                for i, (inputs, labels) in enumerate(self.dataloaders[phase]):
                    y_onehot = torch.zeros(labels.size(0), len(self.class_labels))
                    labels = y_onehot.scatter_(1, labels.view(-1, 1).type(torch.LongTensor), 1)
                    metric_values = self.model.fit(inputs.numpy(), labels.numpy(), phase)

                    # save loss and metrics in one batch
                    for metric, value in zip(self.metrics[phase], metric_values):
                        metric.average_meter.update(value)

                    if not self.cfg['silent']:
                        self._verbose(epoch, phase, i)

                if self.logger:
                    self._record_log(phase, epoch)

                self._update_by_epoch(phase, epoch)

        return self.metrics
