
   .. rubric:: *obsmode* expandable parameters ('int' or 'sd')

   *refdate*

   The date of simulated observation. Examples:
   *refdate='2014/05/21'*

   *hourangle*

   The hour angle of observation, given as a string of various
   possible formats. E.g., "-3:00:00", or "5h". The default setting
   for this parameter is *hourangle='transit'*, which is equivalent
   to 0h.

   *totaltime*

   The total time of an observation. Examples: *totaltime='7200s'* or
   if a number without units, interpreted as the number of times to
   repeat the mosaic.

   .. rubric:: *obsmode='int' expandable parameters*

   *antennalist*

   ASCII file containing antenna positions. Each row has x, y, and z
   coordinates and antenna diameter and name; header lines are
   required to specify the observatory name and coordinate system. If
   the configuration file does not include antenna names, the station
   name will be used instead.

   ::

      #observatory=ALMA
      #COFA=-67.75,-23.02
      #coordsys=LOC (local tangent plane)
      # uid___A002_Xdb6217_X55ec_target.ms
      # x             y               z             diam  station  ant
      -5.850273514   -125.9985379    -1.590364043   12.   A058     DA41
      -19.90369337    52.82680653    -1.892119601   12.   A023     DA42
      13.45860758    -5.790196849    -2.087805181   12.   A035     DA43
      5.606192499     7.646657746    -2.087775605   12.   A001     DA44
      24.10057423    -25.95933768    -2.08466565    12.   A036     DA45

   Standard array configuration files are found in your CASA data
   repository, os.getenv("CASAPATH").split()[0]+"/data/alma/simmos/".
   A string of the form "alma;0.5arcsec" will be parsed into a full
   12m ALMA configuration. If *antennalist=' '*, **simobserve** will
   not produce an interferometric MS. If simulating total power
   observations, be sure to accurately set the parameter
   *sdantlist*.

   *caldirection*

   An unresolved calibrator can be observed interleaved with the
   science pointings. The calibrator is implemented as a point source
   clean component with this specified direction and
   flux= *calflux*.

   *calflux*

   Sets the flux density for the calibrator. Default is set to
   *calflux='1Jy'*.

   .. rubric:: *obsmode='sd' expandable parameters*

   *sdantlist*

   Single-dish antenna position file. If simulating total power
   observations, be sure to accurately set the
   parameter *sdantlist*. If this parameter is left unset,
   **simobserve** assumes the default configuration file for a single
   dish simulation (even if the configuration file is explicitly
   specified in *antennalist*). Default: *sdantlist='aca.tp.cfg'.*

   *sdant*

   The index of the antenna in the list to use for total power.
   Defaults to the first antenna on the list (*sdant=0*).
   Heterogeneous total power "arrays" are not currently supported.

   *thermalnoise*

   Adds thermal noise to the synthesized data. This parameter takes
   two possible values (not including unset ' '):

   -  tsys-atm: J. Pardo's ATM library will be used to construct an
      atmospheric profile for the ALMA site: altitude 5000m, ground
      pressure 650mbar, relhum=20%, a water layer of *user_pwv* at
      altitude of 2km, the sky brightness temperature returned by
      ATM, and internally tabulated receiver temperatures
   -  tsys-manual: instead of using the ATM model, specify the zenith
      sky brightness and opacity manually. Noise is added and then
      the visibility flux scale is referenced above the atmosphere.

   In either mode, noise is calculated using the following
   assumptions:

   -  an antenna spillover efficiency of 0.96,
   -  taper of 0.86,
   -  surface accuracy of 25 and 300 microns for ALMA and EVLA,
      respectively, using the Ruze formula for surface efficiency,
   -  correlator efficiencies of 0.95 and 0.91 for ALMA and EVLA, and
   -  receiver temperatures:

      -  for ALMA: 25, 30, 40, 42, 50, 50, 72, 135, 105, 230 K
         interpolated between 35, 75, 110, 145, 185, 230, 345, 409,
         675, 867 GHz
      -  for EVLA: 500, 70, 60, 55, 100, 130, 350 K interpolated
         between 0.33, 1.47, 4.89, 8.44, 22.5, 33.5, 43.3 GHz
      -  for SMA: 67, 116, 134, 500 K interpolated between 212, 310,
         383, 660 GHz

   These are only approximate numbers and do not take into account
   performance at edges of receiver bands, nor are they guaranteed to
   reflect the most recent measurements. Caveat emptor. Use the
   **sm** tool to add noise if you want more precise control, and use
   the ALMA exposure time calculator for sensitivity numbers in
   proposals.

   .. rubric:: *thermalnoise* expandable parameters

   *t_ground*

   The ambient ground/spillover temperature in K.

   *seed*

   Random number seed for noise generation.

   .. rubric:: *thermalnoise='tsys-atm'* expandable parameters

   *user_pwv*

   The precipitable water vapor at zenith if constructing an
   atmospheric model.

   *thermalnoise='tsys-manual'* expandable parameters

   *t_sky*

   The atmospheric temperature in K.

   *tau0*

   The zenith opacity at observing frequency. See
   `here <https://casaguides.nrao.edu/index.php/Corrupt>`__ for more
   information on noise, in particular how to add a phase screen
   using the toolkit.


   *leakage*

   Adds cross polarization corruption of this fractional magnitude.
   If larger than 0., cross polarization corruption of this fractional magnitude 
   is added (interferometer only) and an MS with all four correlation products 
   is created together with an image with all four Stokes parameters. 
   The value specified for leakage is the standard deviation of the distribution 
   from which the real and imag parts of the complex leakage gains are drawn.
   Typical sensible values for this would be a few %, i.e., leakage in the range 0.02-0.05.
   If one wants to specify a level corresponding to data already calibrated for instrumental 
   polarization, sensible values would be at the level of a few 0.1% (leakage ~ 0.001).

   *graphics*

   View plots on the screen, saved to file, both, or neither.

   *verbose*

   Turns on or off the printing of extra information to the logger
   and terminal.

   *overwrite*

   Overwrites existing files in the project subdirectory. Default:
   False
