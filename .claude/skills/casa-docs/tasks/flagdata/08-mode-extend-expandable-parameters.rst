
   
   .. rubric:: *mode='extend'* expandable parameters
   
   Extend and/or grow flags beyond what the basic algorithms detect.
   This mode will extend the accumulated flags available in the MS,
   regardless of which algorithm created them. It is recommended that
   any autoflag (tfcrop, rflag) algorithm be followed up by a flag
   extension. Extensions will apply only within the selected data,
   according to the settings of *extendpols*, *growtime*, *growfreq*,
   *growaround*, *flagneartime*, and *flagnearfreq*.
   
   .. note:: Runtime summary counts in the logger can sometimes
      report larger flag percentages than what is actually flagged.
      This is because extensions onto already-flagged data-points are
      counted as new flags. An accurate flag count can be obtained
      via the 'summary' mode.
   
   *extendpols*
   
   Extend flags to all selected correlations. Default: True. Options:
   True/False. For example, to extend flags from RR to only RL and
   LR, a data-selection of *correlation='RR,LR,RL'* is required along
   with *extendpols=True*.
   
   *growtime*
   
   For any channel, flag the entire timerange in the current 2D chunk
   (set by *ntime*) if more than X% of the *timerange* is already
   flagged. Default: 50.0. Options: 0.0 - 100.0. This option catches
   the low-intensity parts of time-persistent RFI.
   
   *growfreq*
   
   For any timestep, flag all channels in the current 2D chunk (set
   by data-selection) if more than X% of the channels are already
   flagged. Default: 50.0. Options: 0.0 - 100.0. This option catches
   broad-band RFI that is partially identified by earlier steps.
   
   *growaround*
   
   Flag a point based on the number of flagged points around it.
   Default: False. Options: True/False. For every un-flagged point on
   the 2D time/freq plane, if more than four surrounding points are
   already flagged, flag that point. This option catches some wings
   of strong RFI spikes.
   
   *flagneartime*
   
   Flag points before and after every flagged one, in the
   time-direction. Default: False. Options: True/False. Note that
   this can result in excessive flagging.
   
   *flagnearfreq*
   
   Flag points before and after every flagged one, in the
   frequency-direction. Default: False. Options: True/False. This
   option allows flagging of wings in the spectral response of strong
   RFI. Note that this can result in excessive flagging.
   
   .. rubric:: mode='antint' expandable parameters
   
   This mode flag all integrations in which a specified antenna is
   flagged. This mode operates for an spectral window. It flags any
   integration in which all baselines to a specified antenna are
   flagged, but only if this condition is satisfied in a fraction
   of channels within the spectral window of interest greater than
   a nominated fraction. For simplicity, it assumes that all
   polarization products must be unflagged for a baseline to be
   deemed unflagged. The antint mode implements the flagging
   approach introduced in 'antintflag'
   (https://doi.org/10.5281/zenodo.163546)

   The motivating application for introducing this mode is removal
   of data that will otherwise lead to changes in reference antenna
   during gain calibration, which will in turn lead to corrupted
   polarization calibration.
   
   *antint_ref_antenna*
   
   Check the baselines to this antenna. Note that this is not the
   same as the general 'antenna' parameter of flagdata. The parameter
   antint_ref_antenna is mandatory with the   'antint' mode and
   chooses the antenna for which the fraction of channels flagged
   will be checked.
   
   *minchanfrac*
   
   Minimum fraction of flagged channels required for a baseline  to
   be deemed as flagged. Takes values between 0-1 (float). In this
   mode flagdata does the following for every point in time. It
   checks the fraction of channels flagged for any of the
   polarization products and for every baseline to the antenna of
   interest. If the fraction is higher than this 'minchanfrac'
   threshold then the data are flagged for this pont in time (this
   includes all the rows selected with the flagdata command that have
   that timestamp). This parameter will be ignored if spw specifies a
   channel.
   
   *verbose*

   Print timestamps of flagged integrations to the log.

   .. rubric:: mode='unflag' expandable parameters

   Unflag according to the data selection specified.
   
   .. rubric:: mode='summary' expandable parameters

   List the number of rows and flagged data points for the MS's
   meta-data. The resulting summary will be returned as a Python
   dictionary.
   
   In 'summary' mode, the task returns a dictionary of flagging
   statistics.
   
   Example1:
   
   ::
   
      s = flagdata(..., mode='summary')
   
   s will be a dictionary which contains:
   
   -  s['total']: total number of data
   -  s['flagged']: amount of flagged data
   
   Example2: two summary commands in 'list' mode, intercalating a
   manual flagging command.
   
   ::
   
      s = flagdata(..., mode='list', inpfile=["mode='summary'
      name='InitFlags'", "mode='manual' autocorr=True",
      "mode='summary' name='Autocorr'"])
   
   The dictionary returned in s will contain two dictionaries, one
   for each of the two summary modes.
   
   -  s['report0']['name']: 'InitFlags'
   -  s['report1']['name']: 'Autocorr'
   
   *minrel*
   
   Minimum number of flags (relative) to include in histogram.
   Default: 0.0
   
   *maxrel*
   
   Maximum number of flags (relative) to include in histogram.
   Default: 1.0
   
   *minabs*
   
   Minimum number of flags (absolute, inclusive) to include in
   histogram. Default: 0
   
   *maxabs*
   
   Maximum number of flags (absolute, inclusive) to include in
   histogram. To indicate infinity, use any negative number. Default:
   -1
   
   *spwchan*
   
   List the number of flags per spw and per channel. Default: False
   
   *spwcorr*
   
   Llist the number of flags per spw and per correlation. Default:
   False
   
   *basecnt*
   
   Count the number of flags per baseline. The counts are added to the
   return result dictionary (in the 'baseline'' key) and also printed
   to the log. In addition, counts per antenna/scan are also reported
   and added to the result dictionary (key 'antenna:scan'). Default:
   False
   
   *fieldcnt*
   
   Produce a separated breakdown per field. Default: False
   
   *name*
   
   Name for this summary, to be used as a key in the returned Python
   dictionary. It is possible to call the 'summary' *mode* multiple
   times in 'list' *mode*. When calling the 'summary' *mode* as a
   command in a list, one can give different names to each one of
   them so that they can be easily pulled out of the summary's
   dictionary. Default: 'Summary'

   *action*

   Action to perform in MS/cal table or in the input list of
   parameters. Options: 'none', 'apply', 'calculate'. Default:
   'apply'
