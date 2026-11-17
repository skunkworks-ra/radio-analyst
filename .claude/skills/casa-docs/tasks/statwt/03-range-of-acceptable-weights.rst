
   
   .. rubric:: Range of acceptable weights
   
   The wtrange parameter allows one to specify the acceptable range
   (inclusive, except for zero) for weights. Data with weights
   computed to be outside this range will be flagged. If not
   specified (empty array), all weights are considered to be
   acceptable. If specified, the array must contain exactly two
   non-negative numeric values. Note that data with weights of zero
   are always flagged. The units of the wtrange parameter will always
   match that of the WEIGHT column, even if the task is modifying the
   SIGMA column.

   
   .. rubric:: Including/excluding channels
   
   Channels can be included in the computation of the weights by
   specifying the fitspw parameter. This parameter accepts a valid MS
   channel selection string. Data associated with the selected
   channels will be used in computing the weights; all other channels
   will be excluded from the computation of weights. By default
   (empty string), all channels are included. If the
   Boolean excludechans parameter is set to True, the channel
   selection will be inverted and exclude the selection made
   in fitspw. 
   
   .. warning:: CAUTION: Use of fitspw, when chanbin is not 'spw', may lead to
      the excluded channels being flagged for having less than the
      minimum number of samples (minsamp).

   
   .. rubric:: Preview mode
   
   By setting preview=True, the application is run in preview mode.
   In this mode, no data in the input MS are changed, although the
   amount of data that the application would have flagged is
   reported.

   
   .. rubric:: DATA column
   
   The datacolumn parameter can be specified to indicate which data
   column should be used for computing the weights. The values
   "corrected" for the CORRECTED_DATA column and "data" for the DATA
   column are supported (minimum match, case insensitive). One may
   specify 'residual' in which case the values used are the result of
   the CORRECTED_DATA column minus the model, or 'residual_data' in
   which case the values used are the DATA column minus the model,
   where model is the MODEL_DATA column if it exists, or if it
   doesn't, the virtual source model if one exists, or if that
   doesn't, then no model is used and the 'residual' and
   'residual_data' cases are equivalent to the 'corrected' and 'data'
   cases, respectively. The last two options are to allow for
   operation on timescales or frequency ranges which are larger than
   that over which the sky signal is expected to be constant. This
   situation arises in e.g., OTF mapping, and also perhaps with
   sources with significant spectral structure. In cases where a
   necessary column doesn't exist, an exception will be thrown and no
   data will be changed.
   
   .. note:: NOTE: It is the user's responsibility to ensure that a model
      has been set for all selected fields before using
      datacolumn='residual' or 'residual_data'.

   
   .. rubric:: Return value
   
   In all cases, the mean and variance of the set of all weights
   computed by the application is reported and returned in a
   dictionary with keys 'mean' and 'variance'. Weights for which
   there are corresponding flags (=True) prior to running the
   application are excluded from the computation of these statistics.
   If the WEIGHT_SPECTRUM values are available, they are used to
   compute the statistics, otherwise, the WEIGHT values are used. The
   returned statistics are always computed using the 'CLASSIC'
   algorithm; the value of *statalg* has no impact on how they are
   computed. The units of the the returned statistics will always
   match that of the WEIGHT column, even if the task is modifying the
   SIGMA column.

   
   .. rubric:: Other considerations
   
   Flagged values are not used in computing the weights, although the
   associated weights of these values are updated. If the variance
   for a set of data is 0, all associated flags for that data are set
   to True, and the corresponding weights are set to 0.
