   
   .. rubric:: *mode* expandable parameters (except *mode='list'*)

   *field*
   
   Select fields in mosaic. Use field id(s) or field name(s). [go
   listobs to obtain the list id's or names] Default: '' = all
   fields. If field string is a non-negative integer, it is assumed
   to be a field index otherwise, it is assumed to be a field name.
   Examples: *field='0~2'*, field ids 0,1,2; *field='0,4,5~7'*, field
   ids 0,4,5,6,7; *field='3C286,3C295'*, field named 3C286 and 3C295;
   *field = '3,4C\*'*, field id 3 and all names starting with 4C.
   
   *spw*

   Select data based on spectral window and channels. Default: '' =>
   all spectral windows and channels. Examples: *spw='0~2,4'*,
   spectral windows 0,1,2,4 (all channels); *spw='0:5~61'*, spw 0,
   channels 5 to 61; *spw='<2'*, spectral windows less than 2 (i.e.
   0,1); *spw='0,10,3:3~45'*, spw 0,10 all channels, spw 3, channels
   3 to 45; *spw='0~2:2~6'*; spw 0,1,2 with channels 2 through 6 in
   each; *spw='0:0~10;15~60'*; spectral window 0 with channels
   0-10,15-60; *spw='0:0~10,1:20~30,2:1;2;3'*; spw 0, channels 0-10,
   spw 1, channels 20-30, and spw 2, channels, 1,2 and 3.
   
   .. note:: For modes 'clip', 'tfcrop', and 'rflag',
      channel-ranges can be excluded from flagging by leaving them
      out of the selection range. This is a way to protect known
      spectral-lines from being flagged by the autoflag algorithms.
   
   *antenna*
   
   Select data based on baseline. Default: '' (all). Examples:
   *antenna='DV04&DV06'* baseline DV04-DV06;
   *antenna='DV04&DV06;DV07&DV10'* baselines DV04-DV06 and DV07-DV10;
   *antenna='DV06'* all cross-correlation baselines between antenna
   DV06 and all other available antennas; *antenna='DV04,DV06'* all
   baselines with antennas DV04 and DV06; *antenna='DV06&&DV06'* only
   the auto-correlation baselines for antenna DV06;
   *antenna='DV04&&\*'* cross and auto-correlation baselines between
   antenna DV04 and all other available antennas; *antenna='0~2&&&'*
   only the auto-correlation baselines for antennas in range 0~2   
   
   .. note:: For some antenna-based calibration tables, selecting
      baselines with the & syntax do not apply.
   
   *timerange*

   Select data based on time range. Default: '' (all). Examples:
   *timerange = 'YYYY/MM/DD/hh:mm:ss~YYYY/MM/DD/hh:mm:ss'*;
   
   .. note:: if YYYY/MM/DD is missing date defaults to first day
      in data set.
   
   *timerange='09:14:0~09:54:0'* picks 40 min on first day;
   *timerange='25:00:00~27:30:00'* picks 1 hr to 3 hr 30min on NEXT
   day; *timerange='09:44:00'* pick data within one integration of
   time; *timerange='>10:24:00'* data after this time.
   
   *correlation*
   
   Correlation types or expression. Default: '' (all correlations).
   For modes clip, tfcrop or rflag, the default means ABS_ALL. If the
   input is cal table that does not contain a complex data column,
   the default will fall back to REAL_ALL. Examples:
   *correlation='XX,YY'* or options: Any of 'ABS', 'ARG', 'REAL',
   'IMAG', 'NORM' followed by any of 'ALL', 'I', 'XX', 'YY', 'RR',
   'LL', 'WVR'. 'WVR' refers to the water vapour radiometer of ALMA
   data. For calibration tables, the solutions are: 'Sol1', 'Sol2',
   Sol3, Sol4. When using the 'ARG' option, the values of parameters
   such as clipmin are expected in units of radians.

   .. note:: Correlation selection is not supported for modes other
      than 'clip', 'tfcrop', or 'rflag' in cal tables.
   
   .. note:: The operators ABS, ARG, REAL, etc. are written only
      once as the first value. If more than one correlation is given,
      the operator will be applied to all of them. The expression is
      used only in modes 'clip', 'tfcrop', and 'rflag'.
   
   *scan*
   
   Scan number range. Default: '' (all). Examples: *scan='1~5'*.
   Check 'go listobs' to insure the scan numbers are in order.
   
   *intent*

   Select data based on scan intent. Intent selection is not
   supported for cal tables. Default: '' (all). Examples:
   *intent='*CAL*,*BAND*'*
   
   *array*
   
   Selection based on the antenna array. Array selection is not
   supported for cal tables. Default: '' (all).
   
   *uvrange*
   
   Select data within uvrange (default units meters). Default: ''
   (all). Examples: *uvrange='0~1000klambda'*, uvrange from 0-1000
   kilo-lambda; *uvrange='>4klambda'*, uvranges greater than 4 kilo
   lambda. *uvrange* selection is not supported for cal tables.
   
   *observation*
   
   Selection based on the observation ID. Default: '' (all).
   Examples: *observation='1'* or *observation=1*
   
   *feed*
   
   Selection based on the feed - NOT IMPLEMENTED YET
   
   .. rubric:: *mode='manual'* expandable parameters

   Flag according to the data selection specified. This is the
   default mode (used when the mode is not specified).
   
   *autocorr*
   
   Flag only the auto-correlations. Note that this parameter is only
   active when set to True. If set to False it does NOT mean "do not
   flag auto-correlations". When set to True, it will only flag data
   from a processor of type CORRELATOR. Default: False. Otions: True,
   False
