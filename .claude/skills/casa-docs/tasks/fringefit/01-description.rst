

.. _Description:

Description
   calculates a fringe-fitting (phase/delay/rate) solution
   
   .. warning:: **WARNING: fringefit** is currently an experimental task. Use
      with care and report issues back to the CASA team via the `NRAO
      helpdesk <http://help.nrao.edu/>`__. There is also a Known Issues for fringefit: calibration
      tables made with fringefit in CASA 5.5 will not work in CASA
      5.6 and later.
   
   The **fringefit** task determines phase, delay, delay-rate and
   (optionally) dispersive delay solutions as a function of time
   and spectral window, thus enabling correction of visibility
   phases for errors introduced by the atmosphere, the signal paths
   of the instrument, or other pre-calibration steps. It can
   correct a single scan on a bright source for delay offsets
   between spectral windows, which can result from instrumental
   signal paths (single-band delays), and it can correct multiple
   scans on a source to correct for errors that are variable in
   time (multi-band delay and delay rate). The task uses the model
   data column when present in the MeasurementSet. Fringe fitting
   is primarily useful for VLBI.

   .. rubric:: Introduction

   In Very Long Baseline Interferometry (VLBI), fringe-fitting is
   an essential step which is not typically used for connected
   element arrays such as JVLA and ALMA. The very long baselines
   make observations particularly sensitive to small errors in the
   correlator model (station positions), signal chain, and the
   temporally- and spatially-variable atmosphere. The errors
   manifest themselves as residual delays (which introduce a slope
   when plotting phase against frequency) and delay-rates (which
   cause the phase offset at, say, the center of the band to drift
   as a function of time). Additionally at low frequencies and
   large fractional bandwidths a dispersive delay can be observed
   proportional (in time) to the inverse of the square of frequency
   and therefore proportional to the reciprocal of the frequency in
   phase. These errors can be corrected by observations of a bright
   calibrator source and a phase reference source which is close to
   the target source in projection on the sky.

   Prior to running **fringefit** it is recommended to calibrate
   the amplitudes, as the weights are used by **fringefit** to
   determine the reliability of the fringe detection. A tunable
   SNR-cutoff is implemented to allow weak fringes and
   non-detections to be discarded. Bandpass correction can be done
   either before or after fringe fitting using
   **bandpass**. ** ** Since the CASA **bandpass** is a simple
   complex gain correction, it will be more efficient after fringe
   fitting when VLBI-style geometrical errors are important.

   The algorithm used in **fringefit**, based on the Schwab-Cotton
   algorithm (originally implemented in the AIPS task FRING), has
   two stages. The first step is to look for fringes on each
   baseline to a reference station separately and estimate the SNR
   value for each of these baselines using a Fast Fourier
   Transform. The fringes that pass the SNR requirement are passed
   through to the second step, a global least-squares solver that
   attempts to optimize the solutions and transform them into
   antenna-based solutions for phase, delay, rate and dispersive
   delay. All of the parameters except phase can be included or
   excluded in the solution at this phase using the *paramactive*
   keyword described below; the default is that phase, delay and
   rate are solved but dispersive delay is not, since this matches
   the historical default and the usage we expect to be most common
   in VLBI.
   
   .. note:: **NOTE**: For the multi-band delay, the solutions for the full
      combined spectral window are written for a notional spectral
      window 0. To account for this spectral window in the
      **applycal** step, use the *spwmap* parameter to ensure that
      the solutions are correctly applied to all spectral windows
      (see the Examples tab for details).
      
   .. note:: **NOTE**: Application of fringefit solutions may be optimized by 
      considering use of per-scan interpolation, e.g., via *interp='linearperscan'* 
      or *interp='nearestperscan'*, or in callibrary files, via including a *scanmap* 
      expression. This will force the phase, delay and rate solution 
      interpolation to respect scan boundaries.
   
   .. rubric:: Common calibration solve parameters

   See Solving for
   Calibration for
   more information on the task parameters **fringefit** shares with
   all solving tasks, including data selection, general solving
   properties and arranging prior calibration (i.e., specifying other
   caltables to pre-apply before solving). Also see
   the **rerefant** task documentation for the behavior of reference
   antenna application. Below we describe parameters unique to
   **fringefit** and those common parameters with unique properties. 
   
   .. note:: **NOTE**: Like **gaincal**, fringefit supports passing a list
      of antennas through the *refant* parameter. However
      **fringefit** does not implement the *refantmode* parameter and
      effectively always operates in 'flex' mode, using the next
      antenna from the list as the reference antenna if an antenna is
      not available.
   
   .. rubric:: Parameter descriptions

   .. rubric:: Solution interval: *solint*
   
   The solution interval specified in *solint* (in seconds) is used
   to group data. It is important to make sure that for intervals
   shorter than the scan length, the scan is divided into roughly
   equal sized solution intervals. Avoid selecting a solution
   interval that will lead to intervals containing a single
   integration time, as this will cause an error.
   
   .. rubric:: Combining data for solutions: *combine*
   
   As in other calibration solve tasks, data can be combined over
   different axes. To derive multi-band delay corrections, set
   *combine='spw'.*  See *concatspws* below for additional 
   control of the manner of spw combinations.
   
   .. rubric:: SNR control: *minsnr*
   
   The *minsnr* parameter sets the threshold of the SNR value
   required for the baseline based fringe (FFT stage) to be included
   in the global least-squares minimization.
   
   .. rubric:: Rate-zeroing: *zerorates*
   
   When correcting instrumental delays by solving for each spectral
   window separately, it is usual to apply the corrections derived to
   the entire dataset. Extrapolating the rates in time is
   undesirable, so use of *zerorates=True* will cause no
   time-dependent rate correction to be applied. Note that with this
   option the rates are still solved, and zeroed only when written to
   the table; *paramactive* can be used to turn off solution of rates
   altogether but this is currently not recommended; *zerorates* (and
   its equivalent in other software) has been the standard practice
   in VLBI for a long time, and is likely to remain so.
   
   .. rubric:: Prior correction for parallactic angle: *parang*
   
   Although optional, it is is generally recomended that
   *parang=True* be used for VLBI observations, since parallactic
   angle causes differential phase rates among widely-separated
   antennas that usually should not be included within the
   **fringefit** solution.
   
   .. rubric:: Disabling the global least-squares solver: *globalsolve*
   
   By default, fringe-fit solutions are refined by a global
   least-squares optimization algorithm after the FFT stage. For some
   purposes, it is desirable to use the estimates from the FFT stage
   directly; this can be done by setting *globalsolve* =False. (The
   default is True)
