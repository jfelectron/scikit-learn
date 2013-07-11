# coding: utf-8

# Author: Johannes Schönberger <jschoenberger@demuc.de>
#
# License: BSD 3 clause

import numpy as np

from ..base import BaseEstimator, clone
from ..utils import check_random_state, atleast2d_or_csr
from .base import LinearRegression


class RANSAC(BaseEstimator):
    """RANSAC (RANdom SAmple Consensus) algorithm.

    RANSAC is an iterative algorithm for the robust estimation of parameters
    from a subset of inliers from the complete data set. Each iteration
    performs the following steps:

    1. Select `min_n_samples` random samples from the original data and check
       whether the set of data is valid (see `is_data_valid`).
    2. Fit a model to the random subset (`base_estimator.fit`) and check
       whether the estimated model is valid (see `is_model_valid`).
    3. Classify all data as inliers or outliers by calculating the residuals
       to the estimated model (`base_estimator.predict(X) - y`) - all data
       samples with absolute residuals smaller than the `residual_threshold`
       are considered as inliers.
    4. Save fitted model as best model if number of inlier samples is
       maximal. In case the current estimated model has the same number of
       inliers, it is only considered as the best model if it has better score.

    These steps are performed either a maximum number of times (`max_trials`)
    or until one of the special stop criteria are met (see `stop_n_inliers` and
    `stop_score`). The final model is estimated using all inlier samples of the
    previously determined best model.

    Parameters
    ----------
    base_estimator : object, optional
        Base estimator object which implements the following methods:

         * `fit(X, y)`: Fit model to given  training data and target values.
         * `score(X)`: Returns the mean accuracy on the given test data.

        If no base estimator is specified, by default
        ``sklearn.linear_model.LinearRegression`` is used for float and

        Note that the current implementation only supports regression
        estimators.

    min_n_samples : int (>= 1) or float ([0, 1]), optional
        Minimum number of samples chosen randomly from original data. Treated
        as an absolute number of samples for `min_n_samples >= 1`, treated as a
        relative number `ceil(min_n_samples * X.shape[0]`) for
        `min_n_samples < 1`.

    residual_threshold : float, optional
        Maximum residual for a data sample to be classified as an inlier.

    is_data_valid : callable, optional
        This function is called with the randomly selected data before the
        model is fitted to it: `is_data_valid(X, y)`. If its return value is
        False the current randomly chosen sub-sample is skipped.

    is_model_valid : callable, optional
        This function is called with the estimated model and the randomly
        selected data: `is_model_valid(model, X, y)`. If its return value is
        False the current randomly chosen sub-sample is skipped.

    max_trials : int, optional
        Maximum number of iterations for random sample selection.

    stop_n_inliers : int, optional
        Stop iteration if at least this number of inliers are found.

    stop_score : float, optional
        Stop iteration if score is greater equal than this threshold.

    random_state : integer or numpy.RandomState, optional
        The generator used to initialize the centers. If an integer is
        given, it fixes the seed. Defaults to the global numpy random
        number generator.

    Attributes
    ----------
    estimator_ : object
        Best fitted model (copy of the `base_estimator` object).

    n_trials_ : int
        Number of random selection trials.

    inlier_mask_ : bool array of shape [n_samples]
        Boolean mask of inliers classified as ``True``.

    Raises
    ------
    ValueError: If no valid consensus set could be found.

    References
    ----------
    .. [1] http://en.wikipedia.org/wiki/RANSAC
    .. [2] http://www.cs.columbia.edu/~belhumeur/courses/compPhoto/ransac.pdf
    .. [3] http://www.bmva.org/bmvc/2009/Papers/Paper355/Paper355.pdf
    """

    def __init__(self, base_estimator=None, min_n_samples=0.5,
                 residual_threshold=np.inf, is_data_valid=None,
                 is_model_valid=None, max_trials=100,
                 stop_n_inliers=np.inf, stop_score=np.inf,
                 random_state=None):

        self.base_estimator = base_estimator
        self.min_n_samples = min_n_samples
        self.residual_threshold = residual_threshold
        self.is_data_valid = is_data_valid
        self.is_model_valid = is_model_valid
        self.max_trials = max_trials
        self.stop_n_inliers = stop_n_inliers
        self.stop_score = stop_score
        self.random_state = random_state

    def fit(self, X, y):
        """Fit estimator using RANSAC algorithm.

        Parameters
        ----------
        X : numpy array or sparse matrix of shape [n_samples, n_features]
            Training data.

        y : numpy array of shape [n_samples, n_targets]
            Target values.

        Raises
        ------
        ValueError: If no valid consensus set could be found.
        """
        if self.base_estimator is not None:
            base_estimator = clone(self.base_estimator)
        elif y.dtype.kind == 'f':
            base_estimator = LinearRegression()
        else:
            raise ValueError("`base_estimator` not specified.")

        if 0 < self.min_n_samples < 1:
            min_n_samples = np.ceil(self.min_n_samples * X.shape[0])
        elif self.min_n_samples >= 1:
            min_n_samples = self.min_n_samples
        else:
            raise ValueError("Value for `min_n_samples` must be scalar and "
                             "positive.")

        random_state = check_random_state(self.random_state)

        best_n_inliers = 0
        best_score = np.inf
        best_inlier_mask = None
        best_inlier_X = None
        best_inlier_y = None

        # number of data samples
        n_samples = X.shape[0]
        sample_idxs = np.arange(n_samples)

        X = atleast2d_or_csr(X)
        y = np.asarray(y)

        for n_trials in range(self.max_trials):

            # choose random sample set
            random_idxs = random_state.randint(0, n_samples, min_n_samples)
            rsample_X = X[random_idxs]
            rsample_y = y[random_idxs]

            # check if random sample set is valid
            if self.is_data_valid is not None and not self.is_data_valid(X, y):
                continue

            # fit model for current random sample set
            base_estimator.fit(rsample_X, rsample_y)

            # check if estimated model is valid
            if self.is_model_valid is not None and not \
                    self.is_model_valid(base_estimator, rsample_X, rsample_y):
                continue

            # residuals of all data for current random sample model
            rsample_residuals = np.abs(base_estimator.predict(X) - y)

            # classify data into inliers and outliers
            rsample_inlier_mask = rsample_residuals < self.residual_threshold
            rsample_n_inliers = np.sum(rsample_inlier_mask)

            # less inliers -> skip current random sample
            if rsample_n_inliers < best_n_inliers:
                continue

            # extract inlier data set
            rsample_inlier_idxs = sample_idxs[rsample_inlier_mask]
            rsample_inlier_X = X[rsample_inlier_idxs]
            rsample_inlier_y = y[rsample_inlier_idxs]

            # score of inlier data set
            rsample_score = base_estimator.score(rsample_inlier_X,
                                                 rsample_inlier_y)

            # same number of inliers but worse score -> skip current random
            # sample
            if (rsample_n_inliers == best_n_inliers
                    and rsample_score < best_score):
                continue

            # save current random sample as best sample
            best_n_inliers = rsample_n_inliers
            best_score = rsample_score
            best_inlier_mask = rsample_inlier_mask
            best_inlier_X = rsample_inlier_X
            best_inlier_y = rsample_inlier_y

            # break if sufficient number of inliers or score is reached
            if (best_n_inliers >= self.stop_n_inliers
                    or best_score >= self.stop_score):
                break

        # if none of the iterations met the required criteria
        if best_inlier_mask is None:
            raise ValueError("RANSAC could not find valid consensus set.")

        # estimate final model using all inliers
        base_estimator.fit(best_inlier_X, best_inlier_y)

        self.estimator_ = base_estimator
        self.n_trials_ = n_trials + 1
        self.inlier_mask_ = best_inlier_mask

    def predict(self, X):
        """Predict using the estimated model.

        This is a wrapper for `estimator_.predict(X)`.

        Parameters
        ----------
        X : numpy array of shape [n_samples, n_features]

        Returns
        -------
        C : array, shape = [n_samples]
            Returns predicted values.
        """
        return self.estimator_.predict(X)

    def score(self, X, y):
        """Returns the score of the prediction.

        This is a wrapper for `estimator_.score(X, y)`.

        Parameters
        ----------
        X : numpy array or sparse matrix of shape [n_samples, n_features]
            Training data.

        y : numpy array of shape [n_samples, n_targets]
            Target values.

        Returns
        -------
        z : float
            Score of the prediction.
        """
        return self.estimator_.score(X, y)