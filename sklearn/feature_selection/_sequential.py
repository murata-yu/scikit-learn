"""
Sequential feature selection
"""
import numbers

import numpy as np

import warnings

from ._base import SelectorMixin
from ..base import BaseEstimator, MetaEstimatorMixin, clone
from ..utils._tags import _safe_tags
from ..utils.validation import check_is_fitted
from ..model_selection import cross_val_score


class SequentialFeatureSelector(SelectorMixin, MetaEstimatorMixin,
                                BaseEstimator):
    """Transformer that performs Sequential Feature Selection.

    This Sequential Feature Selector adds (forward selection) or
    removes (backward selection) features to form a feature subset in a
    greedy fashion. At each stage, this estimator chooses the best feature to
    add or remove based on the cross-validation score of an estimator.

    Read more in the :ref:`User Guide <sequential_feature_selection>`.

    .. versionadded:: 0.24

    Parameters
    ----------
    estimator : estimator instance
        An unfitted estimator.

    n_features_to_select : int or float, default='warn'
        If 'auto', the behaviour depends on the `tol` parameter:

        - if `tol` is not None, then features are selected until the score
          improvement does not exceed `tol`.
        - otherwise, half of the features are selected.

        If integer, the parameter is the absolute number of features to select.
        If float between 0 and 1, it is the fraction of features to select.

        .. versionadded:: 1.0
            The default changed from None to 'warn' in 1.0 and will become
            'auto' in 1.2. To keep the same behaviour as with `None`, you
            should manually set `n_features_to_select='auto'` and
            set `tol=None`

    tol : float, default=0.0
        If the score is not incremented by at least `tol` between two
        consecutive feature addition or removal, stop adding or removing even
        if `n_features_to_select` has not been reached. `tol` is enabled only
        when `n_features_to_select` is `'auto'`.

        .. versionadded:: 1.0

    direction : {'forward', 'backward'}, default='forward'
        Whether to perform forward selection or backward selection.

    scoring : str, callable, list/tuple or dict, default=None
        A single str (see :ref:`scoring_parameter`) or a callable
        (see :ref:`scoring`) to evaluate the predictions on the test set.

        NOTE that when using custom scorers, each scorer should return a single
        value. Metric functions returning a list/array of values can be wrapped
        into multiple scorers that return one value each.

        If None, the estimator's score method is used.

    cv : int, cross-validation generator or an iterable, default=None
        Determines the cross-validation splitting strategy.
        Possible inputs for cv are:

        - None, to use the default 5-fold cross validation,
        - integer, to specify the number of folds in a `(Stratified)KFold`,
        - :term:`CV splitter`,
        - An iterable yielding (train, test) splits as arrays of indices.

        For integer/None inputs, if the estimator is a classifier and ``y`` is
        either binary or multiclass, :class:`StratifiedKFold` is used. In all
        other cases, :class:`KFold` is used. These splitters are instantiated
        with `shuffle=False` so the splits will be the same across calls.

        Refer :ref:`User Guide <cross_validation>` for the various
        cross-validation strategies that can be used here.

    n_jobs : int, default=None
        Number of jobs to run in parallel. When evaluating a new feature to
        add or remove, the cross-validation procedure is parallel over the
        folds.
        ``None`` means 1 unless in a :obj:`joblib.parallel_backend` context.
        ``-1`` means using all processors. See :term:`Glossary <n_jobs>`
        for more details.

    Attributes
    ----------
    n_features_to_select_ : int
        The number of features that were selected.

    support_ : ndarray of shape (n_features,), dtype=bool
        The mask of selected features.

    See Also
    --------
    RFE : Recursive feature elimination based on importance weights.
    RFECV : Recursive feature elimination based on importance weights, with
        automatic selection of the number of features.
    SelectFromModel : Feature selection based on thresholds of importance
        weights.

    Examples
    --------
    >>> from sklearn.feature_selection import SequentialFeatureSelector
    >>> from sklearn.neighbors import KNeighborsClassifier
    >>> from sklearn.datasets import load_iris
    >>> X, y = load_iris(return_X_y=True)
    >>> knn = KNeighborsClassifier(n_neighbors=3)
    >>> sfs = SequentialFeatureSelector(knn, n_features_to_select=3)
    >>> sfs.fit(X, y)
    SequentialFeatureSelector(estimator=KNeighborsClassifier(n_neighbors=3),
                              n_features_to_select=3)
    >>> sfs.get_support()
    array([ True, False,  True,  True])
    >>> sfs.transform(X).shape
    (150, 3)
    """
    def __init__(self, estimator, *, n_features_to_select='warn', tol=None,
                 direction='forward', scoring=None, cv=5, n_jobs=None):

        self.estimator = estimator
        self.n_features_to_select = n_features_to_select
        self.tol = tol
        self.direction = direction
        self.scoring = scoring
        self.cv = cv
        self.n_jobs = n_jobs

    def fit(self, X, y):
        """Learn the features to select.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Training vectors.
        y : array-like of shape (n_samples,)
            Target values.

        Returns
        -------
        self : object
        """
        tags = self._get_tags()
        X, y = self._validate_data(
            X, y, accept_sparse="csc",
            ensure_min_features=2,
            force_all_finite=not tags.get("allow_nan", True),
            multi_output=True
        )
        n_features = X.shape[1]

        error_msg = ("n_features_to_select must be either None, an "
                     "integer in [1, n_features - 1] "
                     "representing the absolute "
                     "number of features, or a float in (0, 1] "
                     "representing a percentage of features to "
                     f"select. Got {self.n_features_to_select}")

        if self.n_features_to_select == 'warn':
            # for backwards compability
            warnings.warn("Leaving n_features_to_select to "
                          "None is deprecated in 1.0 and will become 'auto' "
                          "in 1.2. To keep the same behaviour as with None "
                          "(i.e. select half of the features) and avoid "
                          "this warning, you should manually set "
                          "n_features_to_select='auto' and set tol=None.",
                          PendingDeprecationWarning)
            self.n_features_to_select = 'auto'

        if self.n_features_to_select == 'auto':
            if self.tol is not None:
                self.n_features_to_select_ = n_features - 1
            else:
                self.n_features_to_select_ = n_features // 2
        elif isinstance(self.n_features_to_select, numbers.Integral):
            if not 0 < self.n_features_to_select < n_features:
                raise ValueError(error_msg)
            self.n_features_to_select_ = self.n_features_to_select
        elif isinstance(self.n_features_to_select, numbers.Real):
            if not 0 < self.n_features_to_select <= 1:
                raise ValueError(error_msg)
            self.n_features_to_select_ = int(n_features *
                                             self.n_features_to_select)
        else:
            raise ValueError(error_msg)

        if self.direction not in ('forward', 'backward'):
            raise ValueError(
                "direction must be either 'forward' or 'backward'. "
                f"Got {self.direction}."
            )

        cloned_estimator = clone(self.estimator)

        # the current mask corresponds to the set of features:
        # - that we have already *selected* if we do forward selection
        # - that we have already *excluded* if we do backward selection
        current_mask = np.zeros(shape=n_features, dtype=bool)
        n_iterations = (
            self.n_features_to_select_
            if (self.n_features_to_select == 'auto') or (
                     self.direction == 'forward')
            else n_features - self.n_features_to_select_
        )

        old_score = -np.inf
        for _ in range(n_iterations):
            new_feature_idx, new_score = self._get_best_new_feature_score(
                cloned_estimator, X, y, current_mask)

            is_auto_select = (self.tol is not None and
                              self.n_features_to_select == 'auto')
            if is_auto_select and ((new_score - old_score) < self.tol):
                break

            old_score = new_score
            current_mask[new_feature_idx] = True

        if self.direction == 'backward':
            current_mask = ~current_mask

        self.support_ = current_mask
        self.n_features_to_select_ = self.support_.sum()

        return self

    def _get_best_new_feature_score(self, estimator, X, y, current_mask):
        # Return the best new feature to add to the current_mask, i.e. return
        # the best new feature to add (resp. remove) when doing forward
        # selection (resp. backward selection)
        candidate_feature_indices = np.flatnonzero(~current_mask)
        scores = {}
        for feature_idx in candidate_feature_indices:
            candidate_mask = current_mask.copy()
            candidate_mask[feature_idx] = True
            if self.direction == 'backward':
                candidate_mask = ~candidate_mask
            X_new = X[:, candidate_mask]
            scores[feature_idx] = cross_val_score(
                estimator, X_new, y, cv=self.cv, scoring=self.scoring,
                n_jobs=self.n_jobs).mean()

        new_feature_idx = max(
            scores, key=lambda feature_idx: scores[feature_idx])
        return new_feature_idx, scores[new_feature_idx]

    def _get_support_mask(self):
        check_is_fitted(self)
        return self.support_

    def _more_tags(self):
        return {
            'allow_nan': _safe_tags(self.estimator, key="allow_nan"),
            'requires_y': True,
        }
