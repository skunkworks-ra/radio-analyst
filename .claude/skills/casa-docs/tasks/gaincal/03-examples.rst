   

.. _Examples:

Examples
   To solve for G on, say, fields 1 & 2, on a 90s timescale, and do
   so relative to gaincurve and bandpass corrections:
   
   ::
   
      gaincal('data.ms',
              caltable='cal.G90s',          # Write solutions to disk file 'cal.G'
              field='0,1',                  # Restrict field selection
              solint='90s',                 # Solve for phase and amp on a 90s timescale
              gaintable=['cal.B','cal.gc'], # prior bandpass and gaincurve tables
              refant='3')                   # reference antenna
   
   To solve for more rapid tropopheric gains (3s timescale) using the
   above G solution, use *gaintype='T'*:
   
   ::
   
      gaincal(vis='data.ms',
              caltable='cal.T',             # Output table name
              gaintype='T',                 # Solve for T (polarization-independent)
              field='0,1',                  # Restrict data selection to calibrators
              solint='3s',                  # Obtain solutions on a 3s timescale
              gaintable=['cal.B','cal.gc','cal.G90s'],   # all prior cal
              refant='3')                   # reference antenna
   
   To solve for GSPLINE phase and amplitudes, with splines of
   duration 600 seconds:
   
   ::
   
      gaincal('data.ms',
              caltable='cal.spline.ap',
              gaintype='GSPLINE'       #   Solve for GSPLINE
              calmode='ap'             #   Solve for amp & phase
              field='0,1',             #   Restrict data selection to calibrators
              splinetime=600.)         #   Set spline timescale to 10min


.. _Development:

Development
   No additional development details

