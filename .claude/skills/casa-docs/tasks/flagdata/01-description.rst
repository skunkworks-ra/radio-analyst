

.. _Returns:

Returns
   stats (dict) - flag counts, grouped by multiple axes, for
   mode='summary'. RFlag frequency and time thresholds for
   mode='rflag' and action='calculate'


.. _Description:

Description
   This task can flag a MeasurementSet or a calibration table. It has
   two main types of operation. One type will read the parameters
   from the interface and flag using any of the various available
   modes. The other type will read the commands from a text file, a
   list of files or a Python list of strings, containing a list of
   flag commands (each line containing data selection parameters and
   any parameter specific for the mode being requested). Please see
   examples at the end of this help.
   
   It is also possible to only save the parameters set in the
   interface without flagging. The parameters can be saved in the
   FLAG_CMD sub-table or in a text file. Note that when saving to an
   external file, the parameters will be appended to the given file.
   
   The available flagging modes are: 'manual', 'clip', 'shadow',
   'quack', 'elevation', 'tfcrop', 'rflag', 'extend', 'unflag' and
   'summary'. For automatic flagging, it is recommended to combine
   auto-flag modes with 'extend', via the *list* mode.
   
   The current flags can be automatically backed up before applying
   new flags if the parameter *flagbackup* is set. Previous flag
   versions can be recovered using the **flagmanager** task.
   
   .. note::

      on flagging calibration tables:

      **flagdata** can flag many types of calibration tables using
      *mode='manual'*. It can only flag using the auto-flagging
      algorithms ('clip', 'tfcrop', or 'rflag'), the cal tables
      that have the following data columns: CPARAM, FPARAM or SNR.
      For these three modes, the solution elements of the data
      columns are given in the *correlation* parameter using the
      names 'Sol1', 'Sol2', 'Sol3', or 'Sol4'. Note that this is
      an implicit change of the meaning of the *correlation*
      parameter, specific to these three modes. See examples at
      the end of this help on how to flag different cal tables.

      When the input is a calibration table, the modes 'elevation'
      and 'shadow' will be disabled. Data selection for calibration
      tables is limited to *field*, *scan*, *timerange*, *antenna*,
      *spw*  and *observation*. It is only possible to save the
      parameters to an external file. If the calibration table was
      created before CASA 4.1, this task will create a dummy
      OBSERVATION column and OBSERVATION sub-table in the input
      calibration table to adapt it to the new cal table format.
   
      Selecting antennas in some calibration tables have a different
      meaning compared to selecting the MS. Some calibration tables
      such as the antenna-based ones, created with some modes of
      **gencal** or **polcal**, have the ANTENNA2 column set to -1.
      This means that when selecting *antenna='ANT'*, will select the
      whole ANT and not the cross-correlations between ANT and the
      other antennas. Similarly, the baseline syntax do not apply to
      this type of calibration tables. Those values with ampersand do
      not have any meaning when selecting antenna/baselines in
      antenna-based cal tables.

   .. warning:: When flagging calibration tables the following
      combinations of parameters are not supported:

      - Modes 'elevation' and 'shadow'
      - Mode 'manual' with *correlation* parameter

   The task will flag a subset of data based on the following modes
   of operation:
   
   -  'list' = list of flagging commands to apply to MS/cal table
   -  'manual' = flagging based on specific selection parameters
   -  'clip' = clip data according to values
   -  'quack' = remove/keep specific time range at scan beginning/end
   -  'shadow' = remove antenna-shadowed data
   -  'elevation' = remove data below/above given elevations
   -  'tfcrop' = automatic identification of outliers on the
      time-freq plane
   -  'rflag' = automatic detection of outliers based on
      sliding-window RMS filters
   -  'antint' = flag integrations if all baselines to a specified
      antenna are flagged
   -  'extend' = extend and/or grow flags beyond what the basic
      algorithms detect
   -  'summary' = report the amount of flagged data
   -  'unflag' = unflag the specified data 
   
   A progress report line and a partial flagging summary is produced
   in the CASA logger every approximate 10% of the input data (since
   CASA 6.2), when the logger priority level is INFO (default).
   Additional messages are visible when setting a more detailed level
   of logging.

   .. tip::

      The partial or on-the-fly summaries are calculated from the
      flags as they are processed, and, as a consequence, they can
      report misleading counts under certain circumstances, for
      example when using the extend mode (see explanations
      below). Also, when using channel or time averaging the
      on-the-fly summaries can be difficult to interpret as they
      report flag counts for the on-the-fly binned data (see Flags
      and data averaging
      for an explanation of how this can distort the counts or
      percentages of flags). Accurate flag counts for the flags once
      written back to the MeasurementSet can be obtained afterwards
      via the 'summary' mode.
   
   .. rubric:: Parameter descriptions

   *vis*

   Name of input visibility file or calibration table. Default: ''
   (none). Examples: *vis='uid___A002_X2a5c2f_X54.ms'*,
   *vis='cal-X54.B1'*
   
   *mode*
   
   Mode of operation. Options: 'list', 'manual', 'clip', 'quack',
   'shadow', 'elevation', 'tfcrop', 'extend', 'unflag', 'summary'.
   Default: 'manual'
