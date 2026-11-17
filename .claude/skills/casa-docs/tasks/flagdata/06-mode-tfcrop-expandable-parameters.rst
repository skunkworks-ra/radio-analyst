   
   .. rubric:: *mode='tfcrop'* expandable parameters
   
   Flag using the TFCrop autoflag algorithm. For each field, spw,
   timerange (specified by ntime), and baseline:
   
   #. Average visibility amplitudes along time dimension to form an
      average spectrum
   #. Calculate a robust piece-wise polynomial fit for the band-shape
      at the base of RFI spikes. Calculate 'stddev' of (data - fit).
   #. Flag points deviating from the fit by more than N-stddev
   #. Repeat (1-3) along the other dimension.
   
   This algorithm is designed to operate on un-calibrated data (step
   (2)), as well as calibrated data. It is recommended to extend the
   flags after running this algorithm. See the sub-parameter
   *extendflags* below.
   
   *timecutoff*

   Flag threshold in time. Flag all data-points further than N-stddev
   from the fit. This threshold catches time-varying RFI spikes
   (narrow and broad-band), but will not catch RFI that is persistent
   in time. Default: 4.0.
   
   Flagging is done in up to 5 iterations. The stddev calculation is
   adaptive and converges to a value that reflects only the data and
   no RFI. At each iteration, the same relative threshold is applied
   to detect flags. (Step (3) of the algorithm).
   
   *freqcutoff*

   Flag threshold in frequency. Flag all data-points further than
   N-stddev from the fit. Same as *timecutoff*, but along the
   frequency-dimension. This threshold catches narrow-band RFI that
   may or may not be persistent in time. Default: 3.0
   
   *timefit*
   
   Fitting function for the time direction. Default: 'line'. Options:
   'line', 'poly'
   
   A 'line' fit is a robust straight-line fit across the entire
   *timerange* (defined by *ntime*). A 'poly' fit is a robust
   piece-wise polynomial fit across the *timerange*. 
   
   .. note:: A robust fit is computed in upto 5 iterations. At
      each iteration, the stddev between the data and the fit is
      computed, values beyond N-stddev are flagged, and the fit and
      stddev are re-calculated with the remaining points. This stddev
      calculation is adaptive, and converges to a value that reflects
      only the data and no RFI. It also provides a varying set of
      flagging thresholds, that allows deep flagging only when the
      fit best represents the true data. Choose 'poly' only if the
      visibilities are expected to vary significantly over the
      timerange selected by *ntime*, or if there is a lot of strong
      but intermittent RFI.
   

   *freqfit*

   Fitting function for the frequency direction. Same as for the
   *timefit* parameter. Default: 'poly'. Options: 'line', 'poly'.
   Choose 'line' only if you are operating on bandpass-corrected
   data, or residuals, and expect that the bandshape is linear. The
   'poly' option works better on uncalibrated bandpasses with
   narrow-band RFI spikes.
   
   *maxnpieces*
   
   Maxinum number of pieces to allow in the piecewise-polynomial
   fits. Default: 7. Options: 1 - 9. This parameter is used only if
   *timefit* or *freqfit* are chosen as 'poly'. If there is
   significant broad-band RFI, reduce this number. Using too many
   pieces could result in the RFI being fitted in the clean bandpass.
   In later stages of the fit, a third-order polynomial is fit per
   piece, so for best results, please ensure that
   *nchan*/*maxnpieces* is at-least 10.
   
   *flagdimension*
   
   Choose the directions along which to perform flagging. Default:
   'freqtime'; first flag along frequency, and then along time.
   Options: 'time', 'freq', 'timefreq', 'freqtime'. For most cases,
   'freqtime' or 'timefreq' are appropriate, and differences between
   these choices are apparant only if RFI in one dimension is
   significantly stronger than the other. The goal is to flag the
   dominant RFI first. If there are very few (less than 5) channels
   of data, then choose 'time'. Similarly for 'freq'.
   
   *usewindowstats*
   
   Use sliding-window statistics to find additional flags. Default:
   'none'. Options: 'none', 'sum', 'std', 'both'
   
   .. warning:: This parameter is experimental!
   
   The 'sum' option chooses to flag a point, if the mean-value in a
   window centered on that point deviates from the fit by more than
   N-stddev :math:`/ 2.0`.
   
   .. note:: stddev is calculated between the data and fit as
      explained in Step (2). This option is an attempt to catch
      broad-band or time-persistent RFI  that the above polynomial
      fits will mistakenly fit as the clean band. It is an
      approximation to the sumThreshold method found to be effective
      by Offringa et.al (2010) for LOFAR data.
   
   The 'std' option chooses to flag a point, if the 'local' stddev
   calculated in a window centered on that point is larger than
   N-stddev :math:`/2.0`. This option is an attempt to catch noisy
   RFI that is not excluded in the polynomial fits, and which
   increases the global stddev, and results in fewer flags (based on
   the N-stddev threshold).
   
   *halfwin*
   
   Half width of sliding window to use with *usewindowstats*.
   Default: 1 (a 3-point window size). Options: 1,2,3
   
   .. warning:: This is experimental!

   .. rubric:: *mode='tfcrop'* or *'rflag'* expandable parameters

   *extendflags*
   
   Extend flags along time, frequency and correlation. Default: True
   
   .. note:: It is usually helpful to extend the flags along time,
      frequency, and correlation using this parameter, which will run
      the 'extend' mode after 'tfcrop' and extend the flags if more
      than 50% of the timeranges are already flagged, and if more
      than 80% of the channels are already flagged. It will also
      extend the flags to the other polarizations. The user may also
      set extendflags to False and run the 'extend' mode in a second
      step within the same flagging run. See the example below.
