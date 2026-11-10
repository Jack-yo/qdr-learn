"""Training-only imputation/scaling, Ridge and Logistic baselines, no parameter search."""
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def regression(alpha):
    return make_pipeline(SimpleImputer(strategy="median",keep_empty_features=True),StandardScaler(),Ridge(alpha=alpha))


def classifier(c,seed):
    return make_pipeline(SimpleImputer(strategy="median",keep_empty_features=True),StandardScaler(),
                         LogisticRegression(C=c,solver="liblinear",max_iter=300,random_state=seed))


def probabilities(x_train,y_train,x_test,config):
    baseline = float(np.mean(y_train))
    if len(np.unique(y_train))<2:
        return np.full(len(x_test),baseline),baseline,"CONSTANT_SINGLE_CLASS"
    model = classifier(config.logistic_c,config.seed)
    model.fit(x_train,y_train)
    return model.predict_proba(x_test)[:,1],baseline,"UNCALIBRATED_LOGISTIC_BASELINE"
