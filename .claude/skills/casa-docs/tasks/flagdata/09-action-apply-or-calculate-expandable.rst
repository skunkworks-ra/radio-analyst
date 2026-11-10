   
   .. rubric:: *action='apply'* or *'calculate'* expandable
      parameters
   
   action='apply' applies the flags to the MS. action='calculate'
   only calculates the flags but does not write them to the MS. This
   is useful if used together with the display to analyze the results
   before writing to the MS.
   
   *display*
   
   Display data and/or end-of-MS reports at run-time. It needs to
   read a *datacolumn* for the plotting. The default for an MS is
   DATA, but the task will use FLOAT_DATA for a Single-dish MS.
   Default: 'none'. Options: 'none', 'data', 'report', 'both'
   
   'none' --> It will not display anything.
   'data' --> display data and flags per-chunk at run-time, within an
   interactive GUI.
   
   -  This option opens a GUI to show the 2D time-freq planes of the
      data with old and new flags, for all correlations per baseline.
   -  The GUI allows stepping through all baselines (prev/next) in
      the current chunk (set by *ntime*), and stepping to the
      next-chunk.
   -  The **flagdata** task can be quit from the GUI, in case it
      becomes obvious that the current set of parameters is just
      wrong.
   -  There is an option to stop the display but continue flagging.
   
   'report' --> displays end-of-MS reports on the screen.
   'both' --> displays data per chunk and end-of-MS reports on the
   screen
   
   .. rubric:: *action='apply'* expandable parameters

   *flagbackup*
   
   Automatically backup flags before running the tool. Flagversion
   names are chosen automatically, and are based on the *mode* being
   used. Default: True. Options: True/False
   
   .. rubric:: action='' or 'none' description
      
   
   When set to empty or 'none', the underlying tool will not be
   executed and no flags will be produced. No data selection will be
   done either. This is useful when used together with the parameter
   *savepars* to only save the current parameters (or list of
   parameters) to the FLAG_CMD sub-table or to an external file.  

   *savepars*
   
   Save the current parameters to the FLAG_CMD table of the MS or to
   an output text file.
   
   Note that when *display* is set to anything other than 'none',
   *savepars* will be disabled. This is done because in an
   interactive mode, the user may skip data which may invalidate the
   initial input parameters and there is no way to save the
   interactive commands. When the input is a calibration table it is
   only possible to save the parameters to a file.
   
   Default: False. Options: True/False
   
   .. rubric:: savepars=True expandable parameters
   
   *cmdreason*
   
   A string containing a reason to save to the FLAG_CMD table or to
   an output text file given by the *outfile* sub-parameter. If the
   input contains any *reason*, they will be replaced with this one.
   At the moment it is not possible to add more than one *reason*.
   Default: ' ', no *reason* will be added to output. Examples:
   *cmdreason='CLIP_ZEROS'*
   
   *outfile*
   
   Name of output file to save the current parameters. Default: ' ',
   will save the parameters to the FLAG_CMD table of the MS.
   Examples: *outfile='flags.txt'* will save the parameters in a text
   file.
   
   *overwrite*
   
   Overwrite the existing file given in *outfile*. Options:
   True/False. Default: True, it will remove the existing file given
   in *outfile* and save the current flag commands to a new file with
   the same name. When set to False, the task will exit with an error
   message if the file exist.
   
   .. rubric:: SYNTAX FOR COMMANDS GIVEN IN A FILE or LIST OF STRINGS

   .. rubric:: Basic Syntax Rules
   
   #. Commands are strings (which may contain internal "strings")
      consisting of KEY=VALUE pairs separated by one whitespace only.
   
   .. note:: There should be no whitespace between KEY=VALUE.The
      parser first breaks command lines on whitespace, then on "=".
   
   #. Use only ONE white space to separate the parameters (no
      commas). Each key should only appear once on a given command
      line/string.
   #. There is an implicit *mode* for each command, with the default
      being 'manual' if not given.
   #. Comment lines can start with '#' and will be ignored. The
      parser used in **flagdata** will check each parameter name and
      type and exit with an error if the parameter is not a valid
      **flagdata** parameter or of a wrong type.
   
   Example:
   
   ::
   
      scan='1~3' mode='manual'
      # this line will be ignored
      spw='9' mode='tfcrop' correlation='ABS_XX,YY' ntime=51.0
      mode='extend' extendpols=True
      scan='1~3,10~12' mode='quack' quackinterval=1.0
   
   
   .. rubric:: Bibliography

   :sup:`1. Greisen, Eric, Dec 31, 2011. AIPS documentation:
   Section E.5 of the AIPS cookbook (Appendix E: Special
   Considerations for EVLA data calibration and imaging in
   AIPS,` http://www.aips.nrao.edu/cook.html#CEE :sup:`)` `<#ref-cit1>`__
