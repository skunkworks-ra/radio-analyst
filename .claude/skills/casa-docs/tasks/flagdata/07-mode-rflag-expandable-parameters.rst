
   
   .. rubric:: *mode='rflag'* expandable parameters

   Detect outliers based on the RFlag algorithm [1]. The
   polarization expression is given by the *correlation* parameter.
   Iterate through the data in chunks of time. For each chunk,
   calculate local statistics, and apply flags based on user supplied
   (or auto-calculated) thresholds.
   
   -  Time analysis (for each channel):
   
      -  calculate local RMS of real and imaginary visibilities
         within a sliding time window
      -  calculate the median RMS across time windows, deviations of
         local RMS from this median, and the median deviation
      -  flag if local RMS is larger than *timedevscale* :math:`x`
         (medianRMS :math:`+` medianDev)
   
   -  Spectral analysis (for each time):
   
      -  calculate avg of real and imaginary visibilities and their
         RMS across channels
      -  calculate the deviation of each channel from this avg, and
         the median-deviation
      -  flag if deviation is larger than *freqdevscale* :math:`x`
         medianDev
   
   It is recommended to extend the flags after running this
   algorithm. See the sub-parameter *extendflags* below.
   
   Notice that by default the flag implementation in CASA is able to
   calculate the thresholds and apply them on-the-fly (OTF). There is
   a significant performance gain with this approach, as the
   visibilities don't have to be read twice, and therefore is highly
   recommended (see example 1). Otherwise it is possible to reproduce
   the AIPS usage pattern by doing a first run with
   *action='calculate'* and a second run with *action='apply'*. The
   advantage of this approach is that the thresholds are calculated
   using the data from all scans, instead of calculating them for one
   scan only (see example 3).
   
   Example usage :
   
   #. Calculate thresholds automatically per scan, and use them to
      find flags. Specify scale-factor for time-analysis thresholds,
      use default for frequency.
   
      ::
   
         flagdata('my.ms', mode='rflag', spw='9', timedevscale=4.0)
   
   #. Supply noise-estimates to be used with default scale-factors.
   
      ::
   
         flagdata(vis='my.ms', mode='rflag', spw='9', timedev=0.1,
         freqdev=0.5, action='calculate')
   
   #. Two-passes. This replicates the usage pattern in AIPS.
   
      -  The first pass saves commands in output text files, with
         auto-calculated thresholds. Thresholds are returned from
         'rflag' only when *action='calculate'*. The user can edit
         this file before doing the second pass, but the
         python-dictionary structure must be preserved. The
         parameters timedevscale and freqdevscale are not used in
         this first pass.
      -  The second pass applies these commands (*action='apply'*).
   
         ::
   
            flagdata(vis='my.ms', mode='rflag', spw='9,10',
            timedev='tdevfile.txt', freqdev='fdevfile.txt',
            action='calculate')
   
         ::
   
            flagdata(vis='my.ms', mode='rflag', spw='9,10',
            timedev='tdevfile.txt', freqdev='fdevfile.txt',
            action='apply')
   
   With *action='calculate'*, *display='report'* will produce
   diagnostic plots showing data-statistics and thresholds (the same
   thresholds as those written out to 'tdevfile.txt' and
   'fdevfile.txt'). In this second pass, with *action='apply'*, the
   parameters freqdevscale and timedevscale can be used to re-scale
   the thresholds calculated in the first pass.

   .. note:: flagdata is not an interactive plotting tool. If the display parameter is set, the GUI will always show the full data set. Selection parameters only apply to the flags.

   .. note::

      **NOTE1**: The RFlag algorithm was originally developed by
      Eric Greisen in AIPS [1] .

      **NOTE2**: Since this algorithm operates with two passes
      through each chunk of data (time and freq axes), some data
      points get flagged twice. This can affect the flag-percentage
      estimate printed in the logger at runtime. An accurate
      estimate can be obtained via the 'summary' mode.

      **NOTE3**: RFlag calculates statistics across all selected
      correlations. Therefore, if there is a significant amplitude
      difference between parallel-hand and cross-hand correlations,
      or between different solutions in a gain table, it is
      advisable to pre-select subsets of correlations (or sols) on
      which to run one instance of RFlag. For example,
      *correlation='RR,LL'* or *correlation='ABS sol1,sol2'.*
   
   .. note:: Dictionaries returned by action='calculate'.
      Rflag with action='calculate' (the first pass of the
      two-passes usage) can return a dictionary. The dictionary
      holds the freqdev and timedev thresholds calculated in that
      first pass. For example:
   
      thresholds = flagdata(vis='my.ms', mode='rflag',
      action='calculate')
   
      print(thresholds)
   
      {'type': 'list', 'report0': {'type': 'rflag', 'freqdev':
      array([[  1.0e+00,   0.0e+00,   3.13e-02], ... , 'name':
      'Rflag', 'timedev': array([[  1.0e+00,   0.0e+00,   6.8e-03],
      ... ])}, 'nreport': 1}
   
      The timedev and freqdev items from this dictionary can be used
      in the second pass call to flagdata, but their respective
      values need to be passed as separate parameters. For example:
   
      flagdata(vis=ms, mode='rflag', action='apply',
      timedev=thresholds['report0']['timedev'],
      freqdev=thresholds['report0']['freqdev'])
   
      This is an alternative approach (and fully equivalent) to using
      two files to save and reuse the timedev and freqdev values.
   
   *winsize*
   
   Number of timesteps in the sliding time window (fparm(1) in AIPS).
   Default: 3
   
   *timedev*

   Time-series noise estimate (noise in AIPS). Default: [ ].
   Examples: *timedev = 0.5*: Use this noise-estimate to calculate
   flags. Do not recalculate; *timedev = [[1,9,0.2], [1,10,0.5]]*:
   Use noise-estimate of 0.2 for field 1, spw 9, and noise-estimate
   of 0.5 for field 1, spw 10; *timedev = [ ]*: Auto-calculate noise
   estimates; *timedev='timedevfile'*: Auto-calculate noise estimates
   and write them into a file with the name given (any string will be
   interpreted as a file name which will be checked for existence).
   
   *freqdev*
   
   Spectral noise estimate (scutoff in AIPS). This step depends on
   having a relatively-flat bandshape. Same parameter-options as
   *timedev*. Default: [ ]
   
   *timedevscale*
   
   For Step 1 (time analysis), flag a point if local RMS around it is
   larger than *timedevscale* :math:`x` *timedev* (fparm(0) in AIPS).
   This scale parameter is only applied when flagging
   (*action='apply'*) and displaying reports (display option). It is
   not used when the thresholds are simply calculated and saved into
   files (*action='calculate'*, as in the two-passes usage pattern of
   AIPS). Default: 5.0
   
   *freqdevscale*
   
   For Step 2 (spectral analysis), flag a point if local rms around
   it is larger than *freqdevscale* :math:`x` *freqdev* (fparm(10) in
   AIPS). Similarly as with timedevscale, freqdevscale is not used
   when the thresholds are simply calculated and saved into files
   (*action='calculate',* as in the two-passes usage pattern of
   AIPS). Default: 5.0
   
   *spectralmax*
   
   Flag whole spectrum if *freqdev* is greater than *spectralmax*
   (fparm(6) in AIPS). Default: 1E6
   
   *spectralmin*
   
   Flag whole spectrum if *freqdev* is less than *spectralmin*
   (fparm(5) in AIPS). Default: 0.0
