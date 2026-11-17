
   .. rubric:: *mode='clip', 'tfcrop', or 'rflag'* expandable parameters

   *datacolumn*
   
   Column to use for clipping. Default: 'DATA'. Options: MS columns:
   'DATA', 'CORRECTED', 'MODEL', 'RESIDUAL', 'RESIDUAL_DATA',
   'WEIGHT_SPECTRUM', 'WEIGHT', 'FLOAT_DATA'. Cal table columns:
   'FPARAM', 'CPARAM', 'SNR', 'WEIGHT'.                            
   
   .. note::

      RESIDUAL = CORRECTED - MODEL

      RESIDUAL_DATA = DATA - MODEL

      When *datacolumn* is WEIGHT, the task will
      internally use WEIGHT_SPECTRUM. If WEIGHT_SPECTRUM does not
      exist, it will create one on-the-fly based on the values of
      WEIGHT.
   
   *channelavg*
   
   Pre-average data across channels before analyzing visibilities for
   flagging. Partially flagged data is not be included in the average
   unless all data contributing to a given output channel is flagged.
   If present, WEIGHT_SPECTRUM/ SIGMA_SPECTRUM are used to compute a
   weighted average (WEIGHT_SPECTRUM for CORRECTED_DATA and
   SIGMA_SPECTRUM for DATA). Default: False. Options:
   True/False                   
   
   .. note::

      **NOTE1:** Pre-average across channels is meant to be used with
      the auto-flagging methods (clip, tfcrop, rflag) only. In list
      mode, if channelavg is enabled and any other method than
      clip, tfcrop, rflag is used, that is forbidden and flagdata
      will produce an error message and stop. The same applies to
      timeavg.

      **NOTE2**: Pre-average across channels is not supported for
      calibration tables.
   
   *chanbin*

   Bin width for channel average in number of input channels. If a
   list is given, each bin applies to one of the selected SPWs. When
   chanbin is set to 1 all input channels are used for the average to
   produce a single output channel, this behaviour aims to preserve
   backwards compatibility with the previous pre-averaging feature of
   clip mode. Default: 1
   
   *timeavg*
   
   Pre-average data across time before analyzing visibilities for
   flagging. Partially flagged data is not be included in the average
   unless all data contributing to a given output channel is flagged.
   If present, WEIGHT_SPECTRUM/ SIGMA_SPECTRUM are used to compute a
   weighted average (WEIGHT_SPECTRUM for CORRECTED_DATA and
   SIGMA_SPECTRUM for DATA). Otherwise WEIGHT/ SIGMA are used to
   average together data from different integrations. Default: False.
   Options: True/False 
   
   .. note::

      **NOTE1:** Pre-average across time is meant to be used with the
      auto-flagging methods (clip, tfcrop, rflag) only. In list
      mode, if timeavg is enabled and any other method than clip,
      tfcrop, rflag is used, that is forbidden and flagdata will
      produce an error message and stop. The same applies to
      channelavg.

      **NOTE2**: Pre-average across time is not supported for
      calibration tables

   *timebin*

   Bin width for time average in seconds. Default: '0s'

   .. note::

      The auto-flagging methods (clip, tfcrop, rflag) can be used
      together with timeavg and channelavg, and other methods. But
      when one of the auto-flagging methods are employed and timeavg,
      channelavg (or both) are enabled the set of other methods or
      agents that can be used simultaneously is limited to the
      following ones: extendflags, antint, and the display='data' GUI.

      display=’data’ can be added as a parameter in the flagdata call.
      extendflags can be added either in the flagdata call (as a
      subparameter of *tfcrop* or *rflag*) or in the list of commands
      in list mode. antint can only be added in the list of commands
      in list mode, as there is no subparameter of clip, rflag, or
      tfcrop for this.

   .. rubric:: *mode='quack'* expandable parameters
   
   Option to remove specified part of scan beginning/end.
   
   *quackinterval*

   Time in seconds from scan beginning or end to flag. Make time
   slightly smaller than the desired time. Default: 1.0. Type: int or
   float.
   
   *quackmode*
   
   Quack mode. Default: 'beg'. Options:
   
   -  'beg'  ==> flag an interval at the beginning of scan
   -  'endb' ==> flag an interval at the end of scan
   -  'tail' ==> flag all but an interval at the beginning of scan
   -  'end'  ==> flag all but an interval at end of scan
   
   Visual representation of quack mode flagging one scan with 1s
   duration. The following diagram shows what is flagged for each
   quack mode when *quackinterval* is set to 0.25s. The flagged part
   is represented by crosses (+++++++++):
   
   ::
   
                 scan with 1s duration
      --------------------------------------------
      beg
      +++++++++++---------------------------------
                                       endb
      ---------------------------------+++++++++++
                 tail
      -----------+++++++++++++++++++++++++++++++++
      end
      +++++++++++++++++++++++++++++++++-----------
   
   *quackincrement*
   
   Increment quack flagging in time taking into account flagged data
   or not. Default: False. Type: bool
   
   -  False  ==> the quack interval is counted from the scan
      boundaries, as determined by the quackmode parameter,
      regardless if data has been flagged or not.
   -  True   ==> the quack interval is counted from the first
      unflagged data in the scan.
   
   .. warning:: quackincrement = True works based on the state of prior
      flagging, and unless it is the first item in the list the agent
      doing the quacking in list mode doesn't know about the state of
      prior flags. In this case, the command with quackincrement=True
      will be ignored and the task will issue a WARNING.
