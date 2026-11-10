
   
   .. rubric:: *mode='shadow'* expandable parameters
   
   Option to flag data of shadowed antennas. This mode is not
   available for cal tables.
   
   All antennas in the ANTENNA subtable of the MS (and the
   corresponding diameters) will be considered for shadow-flag
   calculations. For a given timestep, an antenna is flagged if any
   of its baselines (projected onto the uv-plane) is shorter than 
   radius :math:`_{1}` :math:`+` radius :math:`_{2}` :math:`-`
   tolerance. The value of 'w' is used to determine which antenna is
   behind the other.

   The uvw values of the baselines are defined as follows:

   #. For the baselines present in the data, the uvw values are taken
      from the UVW column of the corresponding data rows.
   #. If one or more baselines are not present in the data for a given
      timestep, the baseline uvw are additionally calculated using the
      phase-reference center for antenna-pointing direction. In this
      second case, both the antenna positions (expected in ITRF
      spatial coordinate frame) and the phase-reference center are
      converted to J2000 coordinate frame, and the UVW are calculated
      using that frame.

   Shadow mode does not flag rows where the two antennas of the
   baseline are the same, or in other words, antennas do not shadow
   themselves.

   *tolerance*
   
   Amount of shadowing allowed (or tolerated), in meters. A positive
   number allows antennas to overlap in projection. A negative number
   forces antennas apart in projection. Zero implies a distance of
   radius :math:`_{1}` :math:`+` radius :math:`_{2}` between
   antenna centers. Default: 0.0
   
   *addantenna*
   
   It can be either a file name with additional antenna names,
   positions and diameters, or a Python dictionary with the same
   information. You can use the **flaghelper** functions to create
   the dictionary from a file. Default: ''. Type: string or {}
   (dictionary). To create a dictionary inside CASA:
   
   ::
   
      import flaghelper as fh
      antdic = fh.readAntennaList(antfile)
   
   Where antfile is a text file in disk that contains information
   such as:
   
   ::
   
      name=VLA01
      diameter=25.0
      position=[-1601144.96146691, -5041998.01971858, 3554864.76811967]
      name=VLA02
      diameter=25.0
      position=[-1601105.7664601889, -5042022.3917835914, 3554847.245159178]

   
   .. rubric:: *mode='elevation'* expandable parameters

   Option to flag based on antenna elevation. This mode is not
   available for cal tables.
   
   *lowerlimit*
   
   Lower limiting elevation in degrees. Data coming from a baseline
   where one or both antennas were pointing at a strictly lower
   elevation (as function of time), will be flagged. Default: 0.0
   
   *upperlimit*
   
   Upper limiting elevation in degrees. Data coming from a baseline
   where one or both antennas were pointing at a strictly higher
   elevation (as function of time), will be flagged. Default: 90.0
   
   .. rubric:: *mode='tfcrop', 'rflag',\* or *'extend'* expandable parameters

   *ntime*
   
   Time range (in seconds or minutes) over which to buffer data
   before running the algorithm. Options: 'scan' or any other float
   value or string containing the units. Default: 'scan'. Examples:
   *ntime='1.5min'*; *ntime=1.2* (taken in seconds). The dataset will
   be iterated through in time-chunks defined here.
   
   .. warning:: **WARNING**: If *ntime='scan'* and *combinescans=True*, all the
      scans will be loaded at once, thus requesting a lot of memory
      depending on the available spws.
   
   *combinescans*
   
   Accumulate data across scans depending on the value of *ntime*.
   Default: False. This parameter should be set to True only when
   *ntime* is specified as a time-interval (not 'scan'). When set to
   True, it will remove SCAN from the sorting columns, therefore it
   will only accumulate across scans if *ntime* is not set to 'scan'.
