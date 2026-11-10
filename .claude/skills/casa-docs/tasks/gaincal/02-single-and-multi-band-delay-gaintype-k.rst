   
   .. rubric:: Single- and multi-band delay (*gaintype='K'*)
   
   With *gaintype='K'* **gaincal** solves for simple antenna-based
   delays via Fourier transforms of the spectra on baselines to
   (only) the reference antenna. This is not a global fringe fit but
   will be useful for deriving delays from data of reasonable SNR. If
   *combine* includes *'spw'*, multi-band delays solved jointly from
   all selected spectral windows will be determined, and will be
   identified with the first spectral window id in the output
   *caltable*. When applying a multi-band delay table, a non-trivial
   *spwmap* is required to distribute the solutions to all spectral
   windows (fan-out is not automatic).  As of CASA 5.6, multi-band
   delays can be solved using heterogeneous spws (e.g., with
   differing bandwidths, channelizations, etc.).
   
   After solving for delays, a subsequent **bandpass** is recommended
   to describe higher-order channel-dependent variation in the phase
   and amplitude.
   
   .. rubric:: Cross-hand delays (*gaintype='KCROSS'*)
   
   With *gaintype='KCROSS',* **gaincal** solves for a global
   cross-hand delay. This is used only when doing polarimetry. Use
   *parang=True* to apply prior gain and bandpass solutions (only works when all four polarization products are available in the data). This mode
   assumes that all cross-hand data (per spw) share the same
   cross-hand delay residual, which should be the case for a proper
   gain/bandpass calibration. See sections on polarimetry for more
   information on use of this mode.  Multi-band cross-hand delays are
   only supported for homogeneous spws (same bandwidths,
   channelizations, etc.).
   
   
   .. rubric:: Solution normalization: *solnorm, normtype*
   
   Nominally, gain solution amplitudes are implicitly scaled in
   amplitude to satisfy the the effective amplitude ratio between the
   visiibility data and model (as pre-corrected or pre-corrupted,
   respectively, by specified prior calibrations). If *solnorm=True*,
   the solution amplitudes will be normalized so as to achieve an
   effective time- and antenna-relative gain calibration that will
   minimally adjust the global amplitude scale of the visibility
   amplitudes when applied.  This is desirable when the model against
   which the calibration is solved is in some way incomplete w.r.t.
   the net amplitude scale, but a antenna- and time-relative
   calibration is desired, e.g., amplitude-sensitive self-calibration
   when not all of the total flux density has been recovered in the
   visibility model.  The normalization factor is calculated from the
   power gains (squared solution amplitudes) for all antennas and
   times (per spw) according to the the setting of *normtype*.  If
   *normtype='mean'*, (the default), the square root of the mean
   power gain is used to normalize the amplitude gains.  If
   *normtype='median'*, the median is used instead, which can be
   useful to avoid biasing of the normalization by outlier
   amplitudes.  The default for *solnorm* is *solnorm=False*, which
   means no normalization.

   
   .. rubric:: Robust solving:  *solmode, rmsthresh*
   
   .. warning:: Robust solving modes in gaincal are considered experimental.  With more experience and testing in the coming
      development cycles, we will provide more refined advice for use
      of these options.
   
   Nominally (*solmode=''*), gaincal performs an iterative,
   steepest-descent chi-squared minimization for its antenna-based
   gain solution, i.e., minimization of the L2 norm.  Visibility
   outliers (i.e., data not strictly consistent with the assumption
   of antenna-based gains and the supplied visibility model within
   the available SNR) can significantly distort the chi-squared
   gradient calculation, and thereby bias the resulting solution.
   For an outlier on a single baseline, the solutions for the
   antennas in that baseline will tend to be biased in the
   direction of the outlier, and all other antenna solutions in the
   other direction (by a lesser amount consistent with the fraction
   of normal, non-outlying baselines to them).  It is thus
   desirable to dampen the influence of such outliers, and
   solmode/rmshresh provide a mechanism for achieving this.  These
   options apply only to *gaintype='G'* and *'T'*, and will be
   ignored for other options.

   Use of *solmode='L1'* invokes an approximate form of
   minimization of the aggregate absolute deviation of visibilities
   with respect to the model, i.e., the L1 norm.  This is achieved
   by accumulating the nominal chi-squared and its gradient using
   weights divided by (at each iteration of the steepest descent
   process) the current per-baseline absolute residual (i.e., the
   square-root of each baseline's chi-square contribution).  (NB:
   It is not possible to analytically accumulate the gradient of L1
   since the absolute value is not differentiable.)   To avoid an
   over-reliance on baselines with atypically small residuals at
   each interation, the weight adjustments are clamped to a minimum
   (divided) value, and the steepest descent convergence is
   repeated three times with increasingly modest clamping. The net
   effect is to gently but effectively render the weight of
   relative outliers to appropriately damped influence in the
   solution.

   Using *solmode='R'* invokes the normal L2 solution, but attempts
   to identify outliers (relative to apparent aggregate rms) upon
   steepest descent convergence, flag them, and repeat the steepest
   descent.  Since outliers will tend to bias the rms calculation
   initially (and thus possibly render spuriously large rms
   residuals for otherwise good data), outlier detection and
   re-covergence is repeated with increasingly aggressive rms
   thresholds, a sequence specifiable in *rmsthresh*.  By default
   *(rmsthresh=[])* invokes a sequence of 10 thresholds borrowed
   from a traditional implementation found in AIPS:
   [7.0,5.0,4.0,3.5,3.0,2.8,2.6,2.4,2.2,2.5].  Note that the lower
   threshold values are likely to cull visibilites not formally
   outliers, but merely with modestly large residuals still
   consistent with gaussian statistitics, and thereby unnecessarily
   decrease net effective sensitivity in the gain solution (cf
   normal L2), especially for larger arrays where the number of
   baselines likely implies a larger number of visibility residuals
   falling in the modest wings of the distribution.  Thus, it may
   be desirable to set *rmsthresh* manually to a more modest
   sequence of thresholds.  Optimization of *rmsthresh* for modern
   arrays and conditions is an area of ongoing study.

   Use of *solmode='L1R'* combines both the L1 and R modes
   described above, with the iterative clamped L1 loop occuring
   inside the R outliner excision threshold sequence loop.
