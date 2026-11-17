
   .. rubric:: *mode='list'* expandable parameters
   
   Flag according to the data selection and flag commands specified
   in the input list. The input list may come from a text file, a
   list of text files or from a Python list of strings. Each input
   line may contain data selection parameters and any parameter
   specific to the mode given in the line. Default values will be
   used for the parameters that are not present in the line. Each
   line will be taken as a command to the task. If data is
   pre-selected using any of the selection parameters, then flagging
   will apply only to that subset of the MS.
   
   For optimization and whenever possible, the task will create a
   union of the data selection parameters present in the list and
   select only that portion of the MS.
   
   .. note:: The flag commands will be applied only when
      *action='apply'*. If *action='calculate'* the flags will be
      calculated, but not applied. This is useful if *display* is set
      to something other than 'none'. If *action=''* or *'none'*, the
      flag commands will not be applied either. An empty *action* is
      useful only to save the parameters of the list to a file or to
      the FLAG_CMD sub-table.
   
      **NOTE2**: quackincrement = True works based on the state of
      prior flagging, and unless it is the first item in the list the
      agent doing the quacking in list mode doesn't know about the
      state of prior flags. In this case, the command with
      quackincrement=True  will be ignored and the task will issue a
      WARNING.
   
   *inpfile*
   
   Input ASCII file, list of files or a Python list of command
   strings. Default: ''. Options: [ ] with flag commands or [ ] with
   filenames or ' ' with a filename.
   
   .. warning:: **IMPORTANT**: From CASA 4.3 onwards, the parser will be strict
      and accept only valid **flagdata** parameters in the list. It
      will check each parameter name and type and exit with an error
      if any of them is wrong. String values must contain quotes
      around them or the parser will not work. The parser evaluates
      the commands in the list and considers only existing Python
      types.
   
   .. note:: There should be no whitespace between KEY=VALUE since
      the parser first breaks command lines on whitespace, then on
      "=". Use only one whitespace to separate the parameters (no
      commas). Scroll down to the bottom to see a detailed
      description of the input list syntax..
   
   Example1: The following commands can be saved to a file or group
   of files and given to the task (e.g., save it to 'flags.txt'): 
   
   ::
   
      scan='1~3' mode='manual'
      mode='clip' clipminmax=[0,2] correlation='ABS_XX' clipoutside=False
      spw='9' mode='tfcrop' correlation='ABS_YY' ntime=51.0
      mode='extend' extendpols=True
   
   ::
   
      flagdata(vis, mode='list', inpfile='flags.txt')
   
   or
   
   ::
   
      flagdata(vis, mode='list', inpfile=['onlineflags.txt','otherflags.txt'])
   
   Example2: The same commands can be given in a Python list on the
   command line to the task.
   
   ::
   
      cmd=["scan='1~3' mode='manual'",
           "mode='clip' clipminmax=[0,2] correlation='ABS_XX' clipoutside=False",
           "spw='9' mode='tfcrop' correlation='ABS_YY' ntime=51.0",
           "mode='extend' extendpols=True"]
      flagdata(vis,mode='list',inpfile=cmd)


   *reason*
   
   Select flag commands based on REASON(s). Can be a string, or list
   of strings. If *inpfile* is a list of files, the reasons given in
   this parameter will apply to all the files. Default: 'any' (all
   flags regardless of reason). Examples: *reason='FOCUS_ERROR'*;
   *reason=['FOCUS_ERROR', 'SUBREFLECTOR_ERROR']*   
   
   .. note:: **NOTE**: what is within the string is literally matched, e.g.
      reason='' matches only blank reasons, and *reason =
      'FOCUS_ERROR, SUBREFLECTOR_ERROR'* matches this compound reason
      string only. See the syntax for writing flag commands at the
      end of this help. 
   
   *tbuff*
   
   A time buffer or list of time buffers to pad the *timerange*
   parameters in flag commands. When a list of 2 time buffers is
   given, it will subtract the first value from the lower time and
   the second value will be added to the upper time in the range. The
   2 time buffer values can be different, allowing to have an
   irregular time buffer padding to time ranges. If the list contains
   only one time buffer, it will use it to subtract from t0 and add
   to t1. If more than one list of input files is given, *tbuff* will
   apply to all of the flag commands that have *timerange* parameters
   in the files.
   
   Each *tbuff* value should be a float number given in seconds.
   Default: 0.0 (it will not apply any time padding). Example:
   *tbuff=[0.5, 0.8] inpfile=['online.txt','userflags.txt'].* The
   *timerange* parameters in the 'online.txt' file are first
   converted to seconds. Then, 0.5 is subtracted from t0 and 0.8 is
   added to t1, where t0 and t1 are the two intervals given in
   timerange. Similarly, *tbuff* will be applied to any timerange in
   'userflags.txt'.   
   
   .. warning:: **IMPORTANT**: This parameter assumes that timerange = t0 ~ t1,
      therefore it will not work if only t0 or t1 is given.
   
   .. note:: The most common use-case for tbuff is to apply the
      online flags that are created by importasdm when savecmds=True.
      The value of a regular time buffer should be
      *tbuff=0.5\*max* (integration time).


   .. rubric:: *mode='clip'* expandable parameters
   
   Clip data according to values of the following subparameters. The
   polarization expression is given by the *correlation* parameter.
   For calibration tables, the solutions are also given by the
   *correlation* parameter.
   
   *clipminmax*

   Range of data (Jy) that will NOT be flagged. It will always flag
   the NaN/Inf data, even when a range is specified. Default: [ ].
   Example: *clipminmax=[0.0,1.5]*
   
   *clipoutside*
   
   Clip OUTSIDE the range. Default: True. Example:
   *clipoutside=False*, flag data WITHIN the *clipminmax* range.
   
   *clipzeros*
   
   Clip zero-value data. Default: False.
