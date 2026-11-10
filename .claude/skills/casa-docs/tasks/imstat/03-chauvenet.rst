
   .. rubric:: CHAUVENET

   The idea behind this algorithm is to eliminate outliers based on a
   maximum *z-score* parameter value. A *z-score* is the number of
   standard deviations a point is from the mean of a distribution.
   This method thus is meant to be used for (nearly) normal
   distributions. In general, this is an iterative process, with
   successive iterations discarding additional outliers as the
   remaining points become closer to forming a normal distribution.
   Iterating stops when no additional points lie beyond the specified
   *z-score* value, or, if *z-score* is negative, when Chauvenet's
   criterion is met (see below). The parameter *maxiter* can be set
   to a non-negative value to prematurely abort this iterative
   process. When *verbose=T*, the "N-iter" column in the table that
   is logged represents the number of iterations that were executed.

   Chauvenet's criterion allows the target *z-score* to decrease as
   the number of points in the distribution decreases on subsequent
   iterations. Essentially, the criterion is that the probability of
   having one point in a normal distribution at a maximum *z-score*
   of z :sub:`max` must be at least 0.5. z :sub:`max` is therefore
   a function of (only) the number of points in the distribution and
   is given by

   npts = 0.5/erfc(z :sub:`max`/:math:`\sqrt{2}`)

   where erfc() is the complementary error function. As iterating
   proceeds, the number of remaining points decreases as outliers are
   discarded, and so z :sub:`max` likewise decreases. Convergence
   occurs when all remaining points fall within a *z-score* of
   z :sub:`max`. Below is an illustrative table of z :sub:`max`
   values and their corresponding npts values. For example, it is
   likely that there will be a 5-sigma "noise bump" in a perfectly
   noisy image with one million independent elements.

   +-------+-----------------+
   | z max | **npts**        |
   +-------+-----------------+
   | 1.0   | 1               |
   +-------+-----------------+
   | 1.5   | 3               |
   +-------+-----------------+
   | 2.0   | 10              |
   +-------+-----------------+
   | 2.5   | 40              |
   +-------+-----------------+
   | 3.0   | 185             |
   +-------+-----------------+
   | 3.5   | 1,074           |
   +-------+-----------------+
   | 4.0   | 7,893           |
   +-------+-----------------+
   | 4.5   | 73,579          |
   +-------+-----------------+
   | 5.0   | 872,138         |
   +-------+-----------------+
   | 5.5   | 13,165,126      |
   +-------+-----------------+
   | 6.0   | 253,398,672     |
   +-------+-----------------+
   | 6.5   | 6,225,098,696   |
   +-------+-----------------+
   | 7.0   | 195,341,107,722 |
   +-------+-----------------+

   .. rubric:: BIWEIGHT

   The biweight is a robust method to determine the center and width
   of a distribution. It uses the median and median absolute
   deviation to effectively downweight points in the distribution
   that are more than 4 standard deviations from the center of the
   distribution and then computes center (i.e., "location") and the
   width (i.e., "scale") of the distribution. These quantities are
   analogous to the mean and the standard deviation for a standard
   normal distribution. Our implementation is based on the equations
   in Beers 1990  [1]_ and Iglewicz 1983 [2]_.

   The data weights in this algorithm are

   .. math:: w_i = (1 - u_i^2)

   where :math:`u_i` is defined as

   .. math:: u_i = \frac{ x_i - c_{bi} } { c s_{bi} }

   The variable :math:`x_i` is the data values, :math:`c_{bi}` is
   the biweight location, :math:`s_{bi}` is the biweight scale, and
   :math:`c` is a constant. We adopt a value for :math:`c` of 6,
   which gives zero weight to observations more than 4 standard
   deviations from the median. For the initial computation of the
   :math:`u_i` values, :math:`c_{bi}` is set equal to the median of
   the distribution and :math:`s_{bi}` is set equal to the
   normalized MAD (median of the absolute deviation about the
   median), assuming a Gaussian distribution. This value is the MAD
   multiplied by 1.4826, i.e., the value of the probit function at
   0.75.

   The location, :math:`c_{bi}`, is then computed from

   .. math:: c_{bi} = \frac{ \sum_{w_i > 0} x_i  w_i^2 } { \sum_{w_i > 0} w_i^2  }

   where only values of :math:`u_i` which satisfy :math:`|u_i| < 1`
   (:math:`w_i >0`) are included in the sums. Note that the weights
   are zero, not undefined, for points beyond 4 sigma.

   The scale value is computed using

   .. math:: s_{bi}^2 = \frac{ n \sum_{w_i > 0} (x_i - c_{bi})^2 w_i^4} {p \max(1,p-1)}

   where

   .. math:: p = | \sum_{w_i > 0} w_i (5w_i - 4) |

   Again, the above sum includes only data for which
   :math:` | u_i |  < 1` (:math:`w_i >0`). The variable n is the
   number of points for the entire distribution, since points beyond
   4 standard deviations are downweights, not removed.

   The algorithm proceeds as follows.

   1. Compute initial :math:`u_i` values (and hence :math:`w_i`
      values) from the above equation, setting :math:`c_{bi}` equal to
      the median of the distribution and :math:`s_{bi}` equal to the
      normalized MAD.
   2. Compute the initial value of the scale using the
      :math:`w_i` values computed in step 1 using the equation for
      :math:`s_{bi}`.
   3. Recompute :math:`u_i` and :math:`w_i` values using the
      most recent previous scale and location values.
   4. Compute the location using the :math:`u_i` and
      :math:`w_i` values from step 3 and the equation for
      :math:`c_{bi}`.
   5. Recompute :math:`u_i` and :math:`w_i` values using the
      most recent previous scale and location values.
   6. Compute the new scale value using the the :math:`u_i` and
      :math:`w_i` values computed in step 5 and the value of the
      location computed in step 4.
   7. Steps 3 - 6 are repeated until convergence occurs or the
      maximum number of iterations (specified in the *niter*
      parameter) is reached. The convergence criterion is given by


   .. math:: | (s_{bi} - s_{bi,prev})/s_{bi,prev} | < 0.03  \sqrt{ \frac{0.5}{n - 1}}

   where :math:`s_{bi,prev}` is the value of the scale
   computed in the previous iteration.

   In the special case where *niter* is specified to be negative, the
   scale and location will be computed directly with no iteration.

   1. Compute :math:`u_i` and :math:`w_i` values using the
      median for the location and the normalized MAD as the scale.
   2. Compute the location and scale (which can be carried out
      simultaneously) using the :math:`u_i` and :math:`w_i` values
      computed in step 1. The value of the location used in the scale
      computation is just the median.

   The only keys present in the returned dictionary are 'mean'
   (location), 'sigma' (scale), 'npts', 'min', and 'max' to maximize
   speed. The last three represent the values using the entire
   distribution. Note that the biweight algorithm does not support
   computation of quantile-like values (median, medabsdevmed, q1, q3,
   and iqr), so setting *robust=True* will cause a warning message to
   be logged regarding that, and the computation will proceed. If you
   want to compute these quantities in addition those values
   calculated here, re-run **imstat** with selecting another
   algorithm.
