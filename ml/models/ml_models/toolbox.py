import logging
import pickle

logger = logging.getLogger(__name__)

import numpy as np
from sklearn.exceptions import NotFittedError
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import log_loss
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.naive_bayes import GaussianNB


def ml_model_manager_args(parser):

    ml_model_manager_parser = parser.add_argument_group("ML model hyper parameters")
    ml_model_manager_parser.add_argument('--C', type=float, default=0.01)
    ml_model_manager_parser.add_argument('--svm-kernel', choices=['linear', 'rbf'], default='linear')
    ml_model_manager_parser.add_argument('--early-stopping-round', type=int, default=10)

    return parser


from dataclasses import dataclass, field
from typing import List
from ml.utils.enums import SVMKernelType


@dataclass
class MlModelManagerConfig:     # ML model hyper parameters
    # TODO This is only for SVM ?
    C: float = 0.01
    svm_kernel: SVMKernelType = SVMKernelType.linear
    early_stopping_round: int = 10


class BaseMLPredictor:
    def __init__(self, class_labels, cfg):
        self.class_labels = class_labels
        self.cfg = cfg
        self.fitted = False

    def save_model(self, fname):
        with open(fname, 'wb') as f:
            pickle.dump(self.model, f)

    def load_model(self, fname):
        with open(fname, 'rb') as f:
            self.model = pickle.load(f)
        self.fitted = True

    def fit(self, x, y) -> np.float:
        logger.info('Now fitting...')
        self.fitted = True
        # lossを返却

        self.model.fit(x, y)
        return log_loss(y, self.model.predict_proba(x), labels=self.class_labels)

    # def partial_fit(self, x, y, eval_x=None, eval_y=None):
    #     not_improved_round = 0
    #     best_loss = 1e+8
    #
    #     for batch in range(x.shape[0] // self.cfg['batch_size']):
    #         s_idx, e_idx = batch * self.cfg['batch_size'], (batch + 1) * self.cfg['batch_size']
    #         batch_x, batch_y = x[s_idx:e_idx], y[s_idx:e_idx]
    #         self.model.partial_fit(batch_x, batch_y)
    #         loss = log_loss(eval_y, self.model.predict_proba(eval_x), labels=self.class_labels)
    #
    #         if loss < best_loss:
    #             not_improved_round = 0
    #             best_loss = loss
    #         else:
    #             not_improved_round += 1
    #
    #         if not_improved_round == self.cfg['early_stopping_round']:
    #             pass
    #     return list(self.model.best_score_.keys())[-1]

    def predict(self, x):
        if not self.fitted:
            raise NotFittedError(f'This MLModel instance is not fitted yet.')
        return self.model.predict(x)

    def predict_proba(self, x) -> np.float32:
        return self.model.predict_proba(x).astype(np.float32)


class KNN(BaseMLPredictor):
    def __init__(self, class_labels, cfg):
        super(KNN, self).__init__(class_labels, cfg)
        self.model = KNeighborsClassifier(n_neighbors=len(self.class_labels), n_jobs=-1)

    def predict_proba(self, x):
        return np.eye(len(self.class_labels))[self.model.predict(x).astype(int)].astype(np.float32)


class SGDC(BaseMLPredictor):
    def __init__(self, class_labels, cfg):
        class_weight = dict(zip(class_labels, cfg['loss_weight']))
        self.model = SGDClassifier(loss='log', alpha=cfg['lr'], shuffle=False, n_jobs=cfg['n_jobs'],
                                   random_state=cfg['seed'], learning_rate='optimal', class_weight=class_weight,
                                   verbose=False)
        super(SGDC, self).__init__(class_labels, cfg)


class SVM(BaseMLPredictor):
    def __init__(self, class_labels, cfg):

        class_weight = 'balanced' if cfg['loss_weight'] == 'balanced' else dict(zip(class_labels, cfg['loss_weight']))
        self.model = SVC(C=cfg['C'], kernel=cfg['svm_kernel'], class_weight=class_weight, probability=True,
                         random_state=cfg['seed'], verbose=False)
        super(SVM, self).__init__(class_labels, cfg)


class NaiveBayes(BaseMLPredictor):
    def __init__(self, class_labels, cfg):
        self.model = GaussianNB()
        super(NaiveBayes, self).__init__(class_labels, cfg)
