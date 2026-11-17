

.. _Returns:

Returns
   out (dict) - statistics of the solutions found, grouped by SPW and
   antenna, including solutions expected, above *minblperant*, and
   above *minsnr*, as well as what antennas were used as reference.
   Also gives information on data selection and calibration tables used.


.. _Description:

Description
   The complex time-dependent gains for each antenna/spwid are
   determined from the ratio of the data column (raw data), divided
   by the model column, for the specified data selection. The gains
   can be obtained for a specified solution interval for each
   spectral window, or by a spline fit to all spectral windows
   simultaneously. Any specified prior calibrations (e.g., bandpass)
   will be applied on the fly.
   
   .. rubric:: Introduction

   The fundamental calibration to be done on your interferometer data
   is to calibrate the antenna-based gains as a function of time,
   using **gaincal**. Systematic time-dependent complex gain errors
   are almost always the dominant calibration effect, and a solution
   for them is almost always necessary before proceeding with any
   other calibration solve. Traditionally, this calibration type has
   been a catch-all for a variety of similar effects, including: the
   relative amplitude and phase gain for each antenna/polarization,
   phase and amplitude drifts in the electronics of each antenna,
   amplitude response as a function of elevation (gain curve), and
   tropospheric amplitude and phase effects. In CASA, it is possible
   to handle many of these specific effects separately, as available
   information, circumstances, and required accuracy warrant, but if
   accuracy is not paramount it is still possible to solve for the
   net effect using a quick-and-dirty **gaincal**. In fact,
   **gaincal** is often used for an initial exploration of a dataset,
   to find data problems, etc. Also, a provisional gaincal solution
   can be used as prior calibration to optimize bandpass
   calibration.  Such gaincal solutions are typically discarded.
   
   It is best to have determined a (constant or slowly-varying)
   bandpass from the frequency channels by solving for the
   **bandpass**, and to include any other ancillary calibration that
   may be available via **gencal** (e.g., gaincurve, antenna position
   corrections, opacity, etc.).
   
   .. rubric:: Common calibration solve parameters
   
   See Solving for
   Calibration for
   more information on the task parameters **gaincal** shares with
   all solving tasks, including data selection, general solving
   properties and arranging prior calibration. Also see the
   **rerefant** task documentation for the behavior of reference
   antenna application. Below we describe parameters unique to
   **gaincal**, and those common parameters with unique properties.
   
   .. rubric:: Gain calibration types: *gaintype*
   
   The *gaintype* parameter selects the type of gain solution to
   compute. For complex gain calibration, the choices are *'T'*,
   *'G'*, and *'GSPLINE'*. The **gaincal** task also supports
   rudimetary delay solutions using *'K'* and *'KCROSS'*.
   
   .. rubric:: Polarization-dependent sampled gain (*gaintype='G'*)
   
   Generally speaking, *gaintype='G'* can represent any
   multiplicative polarization- and time-dependent complex gain
   effect downstream of the polarizers. (Polarization- and
   time-independent effects upstream of the polarizers may also be
   treated implicitly with G.) Multi-channel data (per spectral
   window) will be averaged in frequency before solving (use
   calibration type B to solve for frequency-dependent effects within
   each spectral window).
   
   .. rubric:: Polarization-independent sampled gain (*gaintype='T'*)
   
   At high radio frequencies (>10 GHz), it is often the case that the
   most rapid time-dependent gain errors are introduced by the
   troposphere, and are polarization-*independent*. It is therefore
   unnecessary to solve for separate time-dependent solutions for
   both polarizations, as is the case for *gaintype='G'*. Thus
   *gaintype='T'* is available to calibrate such tropospheric
   effects, differing from G only in that a single common solution
   for both polarizations is determined. In cases where only one
   polarization is observed, *gaintype='T'* is adequate to describe
   the time-dependent complex multiplicative gain calibration
   entirely. For the dual-polarization case, it is necessary to
   ensure that the two polarizations are, in fact, coherent by using
   a prior G or (unnormalized) bandpass calibration. 
   
   .. rubric:: Spline gains (*gaintype='GSPLINE'*)
   
   At high radio frequencies, where tropospheric phase fluctuates
   rapidly, it is often the case that there is insufficient
   signal-to-noise to obtain robust G or T solutions on timescales
   short enough to track the variation. In this case it is desirable
   to solve for a best-fit functional form for each antenna using the
   GSPLINE solver. This fits a time-series of cubic B-splines to the
   phase and/or amplitude of the calibrator visibilities.
   
   The *combine* parameter can be used to combine data across
   spectral windows, scans, and fields. Note that if you want to use
   *combine='field'*, then all fields used to obtain a GSPLINE
   amplitude solution must have models with accurate relative flux
   densities. Use of incorrect relative flux densities will introduce
   spurious variations in the GSPLINE amplitude solution.
   
   The GSPLINE solver requires a number of unique additional
   parameters, compared to ordinary G and T solving. The
   sub-parameters are:
   
   ::
   
      gaintype         =  'GSPLINE'   #   Type of solution (G, T, or GSPLINE)
           splinetime  =     3600.0   #   Spline (smooth) timescale (sec), default=1 hours
           npointaver  =          3   #   Points to average for phase wrap
           phasewrap   =        180   #   Wrap phase when greater than this
   
   The duration of each spline segment is controlled by *splinetime*.
   The *splinetime* will be adjusted automatically such that an
   integral number of equal-length spline segments will fit within
   the overall range of data.
   
   Phase splines require that cycle ambiguities be resolved prior to
   the fit; this operation is controlled by *npointaver* and
   *phasewrap*. The *npointaver* parameter controls how many
   contiguous points in the time-series are used to predict the cycle
   ambiguity of the next point in the time-series, and *phasewrap*
   sets the threshold phase jump (in degrees) that would indicate a
   cycle slip. Large values of *npointaver* improve the SNR of the
   cycle estimate, but tend to frustrate ambiguity detection if the
   phase rates are large. The *phasewrap* parameter may be adjusted
   to influence when cycles are detected. Generally speaking, large
   values (>180 degrees) are useful when SNR is high and phase rates
   are low. Smaller values for *phasewrap* can force cycle slip
   detection when low SNR conspires to obscure the jump, but the
   algorithm becomes significantly less robust. More robust
   algorithms for phase-tracking are under development (including
   traditional fringe-fitting).
   
   .. warning:: GSPLINE solutions cannot be used in fluxscale. You should do at
      least some long-timescale G amplitude solutions to establish
      the flux scale, then do GSPLINE in phase before or after to fix
      up the short timescale variations. Note also that the phase
      tracking algorithm in GSPLINE needs some improvement.
