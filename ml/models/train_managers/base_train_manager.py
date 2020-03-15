import argparse
import logging
import random
import time
from abc import ABCMeta
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
import torch
from ml.models.model_managers.base_model_manager import model_args
from ml.models.model_managers.ml_model_manager import MLModelManager, supported_ml_models
from ml.models.model_managers.nn_model_manager import NNModelManager, supported_nn_models, supported_pretrained_models
from sklearn.metrics import confusion_matrix
from ml.utils.logger import TensorBoardLogger
from typing import Tuple, List, Union
from ml.utils.utils import Metrics


supported_models = supported_ml_models + supported_nn_models + list(supported_pretrained_models.keys())


def type_float_list(args) -> Union[List[float], str]:
    if args in ['same', None]:
        return args
    return list(map(float, args.split(',')))


def train_manager_args(parser) -> argparse.ArgumentParser:

    train_manager_parser = parser.add_argument_group("Model manager arguments")
    train_manager_parser.add_argument('--train-path', help='data file for training', default='input/train.csv')
    train_manager_parser.add_argument('--val-path', help='data file for validation', default='input/val.csv')
    train_manager_parser.add_argument('--test-path', help='data file for testing', default='input/test.csv')

    train_manager_parser.add_argument('--model-type', default='cnn', choices=supported_models)
    train_manager_parser.add_argument('--gpu-id', default=0, type=int, help='ID of GPU to use')
    train_manager_parser.add_argument('--transfer', action='store_true', help='Transfer learning from model_path')

    # optimizer params
    optim_param_parser = parser.add_argument_group("Optimizer parameter arguments for learning")
    optim_param_parser.add_argument('--optimizer', default='adam', help='Type of optimizer. ',
                                    choices=['sgd', 'adam', 'rmsprop'])
    optim_param_parser.add_argument('--lr', '--learning-rate', default=1e-3, type=float, help='initial learning rate')
    optim_param_parser.add_argument('--momentum', default=0.9, type=float, help='momentum')
    optim_param_parser.add_argument('--weight-decay', default=0.0, type=float, help='weight-decay')
    optim_param_parser.add_argument('--learning-anneal', default=1.01, type=float,
                                    help='Annealing applied to learning rate every epoch')

    hyper_param_parser = parser.add_argument_group("Hyper parameter arguments for learning")
    hyper_param_parser.add_argument('--batch-size', default=32, type=int, help='Batch size for training')
    hyper_param_parser.add_argument('--epoch-rate', default=1.0, type=float, help='Data rate to to use in one epoch')
    hyper_param_parser.add_argument('--n-jobs', default=4, type=int, help='Number of workers used in data-loading')
    hyper_param_parser.add_argument('--loss-weight', default='same', type=type_float_list,
                                    help='The weights of all class about loss')
    hyper_param_parser.add_argument('--sample-balance', default=None, type=type_float_list,
                                    help='Sampling label balance from dataset.')
    hyper_param_parser.add_argument('--epochs', default=20, type=int, help='Number of training epochs')
    hyper_param_parser.add_argument('--tta', default=0, type=int, help='Number of test time augmentation ensemble')
    hyper_param_parser.add_argument('--mixup-alpha', default=0.0, type=float, help='Beta distirbution alpha for mixup.')
    hyper_param_parser.add_argument('--retrain-epochs', default=5, type=int, help='Number of training epochs')

    # General parameters for training
    general_param_parser = parser.add_argument_group("General parameters for training")
    general_param_parser.add_argument('--model-path', help='Path to save model', default='../output/models/sth.pth')
    general_param_parser.add_argument('--checkpoint-path', help='Model weight file to load model',
                                      default=None)
    general_param_parser.add_argument('--task-type', help='Task type. regress or classify',
                                      default='classify', choices=['classify', 'regress'])
    general_param_parser.add_argument('--seed', default=0, type=int, help='Seed to generators')
    general_param_parser.add_argument('--cuda', dest='cuda', action='store_true', help='Use cuda to train model')
    general_param_parser.add_argument('--amp', dest='amp', action='store_true', help='Mixed precision training')
    general_param_parser.add_argument('--cache', action='store_true', help='Make cache after preprocessing or not')

    # Logging of criterion
    logging_parser = parser.add_argument_group("Logging parameters")
    logging_parser.add_argument('--log-id', default='results', help='Identifier for tensorboard run')
    logging_parser.add_argument('--tensorboard', dest='tensorboard', action='store_true', help='Turn on tensorboard graphing')
    logging_parser.add_argument('--log-dir', default='../visualize/tensorboard', help='Location of tensorboard log')

    parser = model_args(parser)

    return parser


@contextmanager
def simple_timer(label) -> None:
    start = time.time()
    yield
    end = time.time()
    logger.info('{}: {:.3f}'.format(label, end - start))


class BaseTrainManager(metaclass=ABCMeta):
    def __init__(self, class_labels, cfg, dataloaders, metrics):
        self.class_labels = class_labels
        self.cfg = cfg
        self.dataloaders = dataloaders
        self.device = self._init_device()
        self.model_manager = self._init_model_manager()
        self._init_seed()
        self.logger = self._init_logger()
        self.metrics = metrics
        Path(self.cfg['model_path']).parent.mkdir(exist_ok=True, parents=True)

    @staticmethod
    def check_keys_from_dict(must_contain_keys, dic) -> None:
        for key in must_contain_keys:
            assert key in dic.keys(), f'{key} must be in {str(dic)}'

    def _init_model_manager(self) -> Union[NNModelManager, MLModelManager]:
        self.cfg['input_size'] = list(self.dataloaders.values())[0].get_input_size()

        if self.cfg['model_type'] in supported_nn_models + list(supported_pretrained_models.keys()):
            if self.cfg['model_type'] in ['rnn']:
                if self.cfg['batch_norm']:
                    self.cfg['batch_norm_size'] = list(self.dataloaders.values())[0].get_batch_norm_size()
                self.cfg['seq_len'] = list(self.dataloaders.values())[0].get_seq_len()
            elif self.cfg['model_type'] in ['logmel_cnn', 'cnn', 'cnn_rnn'] + list(supported_pretrained_models.keys()):
                self.cfg['image_size'] = list(self.dataloaders.values())[0].get_image_size()
                self.cfg['n_channels'] = list(self.dataloaders.values())[0].get_n_channels()

            return NNModelManager(self.class_labels, self.cfg)

        elif self.cfg['model_type'] in supported_ml_models:
            return MLModelManager(self.class_labels, self.cfg)
        
    def _init_seed(self) -> None:
        # Set seeds for determinism
        torch.manual_seed(self.cfg['seed'])
        torch.cuda.manual_seed_all(self.cfg['seed'])
        np.random.seed(self.cfg['seed'])
        random.seed(self.cfg['seed'])

    def _init_device(self) -> torch.device:
        if self.cfg['cuda'] and self.cfg['model_type'] in supported_nn_models + list(supported_pretrained_models.keys()):
            device = torch.device("cuda")
            torch.cuda.set_device(self.cfg['gpu_id'])
        else:
            device = torch.device("cpu")

        return device

    def _init_logger(self) -> TensorBoardLogger:
        if self.cfg['tensorboard']:
            return TensorBoardLogger(self.cfg['log_id'], self.cfg['log_dir'])

    def _record_log(self, phase, epoch) -> None:
        values = {}

        for metric in self.metrics[phase]:
            values[f'{phase}_{metric.name}_mean'] = metric.average_meter.average
        self.logger.update(epoch, values)

    def _predict(self, phase) -> Tuple[np.array, np.array]:
        raise NotImplementedError

    def _average_tta(self, pred_list, label_list):
        new_pred_list = np.zeros((-1, pred_list.shape[0] // self.cfg['tta']))
        for label in range(pred_list.shape[1]):
            new_pred_list[:, label] = pred_list[:, label].reshape(self.cfg['tta'], -1).mean(axis=0)
        pred_list = new_pred_list
        label_list = label_list[:label_list.shape[0] // self.cfg['tta']]

        return pred_list, label_list

    def train(self, model_manager=None, with_validate=True, only_validate=False) -> Tuple[Metrics, np.array]:
        raise NotImplementedError

    def test(self, return_metrics=False, load_best=True, phase='test') -> Union[Tuple[np.array, np.array, Metrics],
                                                                                Tuple[np.array, np.array]]:
        if load_best:
            self.model_manager.load_model()

        pred_list, label_list = self._predict(phase=phase)
        if self.cfg['return_prob']:
            pred_onehot = torch.from_numpy(pred_list)
            pred_list = np.argmax(pred_list, axis=1)

        logger.debug(f'Prediction info:{pd.Series(pred_list).describe()}')

        for metric in self.metrics['test']:
            if metric.name == 'loss':
                if self.cfg['task_type'] == 'classify':
                    y_onehot = torch.zeros(label_list.shape[0], len(self.class_labels))
                    y_onehot = y_onehot.scatter_(1, torch.from_numpy(label_list).view(-1, 1).type(torch.LongTensor), 1)
                    if not self.cfg['return_prob']:
                        pred_onehot = torch.zeros(pred_list.shape[0], len(self.class_labels))
                        pred_onehot = pred_onehot.scatter_(1, torch.from_numpy(pred_list).view(-1, 1).type(torch.LongTensor), 1)
                    loss_value = self.model_manager.criterion(pred_onehot.to(self.device), y_onehot.to(self.device)).item()
                elif self.cfg['model_type'] in ['rnn', 'cnn', 'cnn_rnn']:
                    loss_value = self.model_manager.criterion(torch.from_numpy(pred_list).to(self.device),
                                                              torch.from_numpy(label_list).to(self.device))
            else:
                loss_value = 10000000

            metric.update(loss_value=loss_value, preds=pred_list, labels=label_list)
            logger.info(f"{phase} {metric.name}: {metric.average_meter.value :.4f}")
            metric.average_meter.update_best()

        if self.cfg['task_type'] == 'classify':
            confusion_matrix_ = confusion_matrix(label_list, pred_list,
                                                 labels=list(range(len(self.class_labels))))
            logger.info(f'Confusion matrix: \n{confusion_matrix_}')

        if return_metrics:
            if self.cfg['return_prob']:
                return pred_onehot.numpy(), label_list, self.metrics
            else:
                return pred_list, label_list, self.metrics
        return pred_list, label_list

    def infer(self, load_best=True, phase='infer') -> np.array:
        if load_best:
            self.model_manager.load_model()

        pred_list, _ = self._predict(phase=phase)

        return pred_list
