
   .. rubric:: Using the Predefined Standards


   For the VLA, the default source models are customarily point
   sources defined by the *’Baars’*, *’Perley 90’*, *’Perley-Taylor
   99’*, *’Perley-Butler 2010’*, time-variable *’Perley-Butler 2013’*,
   *'Perley-Butler 2017'*, *’Scaife-Heald 2012’*, or
   *’Stevens-Reynolds 2016’* flux density scales (See Flux
   Calibrator Models
   for details; *’Perley-Butler 2017’* is the current standard by
   default), or point sources of unit flux density if the flux
   density is unknown. When 'Perley-Bulter 2017' is used and if any
   part of the frequencies of the relevant visibility data are
   outside the valid frequency range for each individual source as
   listed in Flux Calibrator Models,
   **setjy** issues warning log messages while it still proceeds to
   calcuate the flux densities and set the model visibility.

   Most calibrator sources are based on radio emission from quasars
   and jets. The spectral indices of these sources are such that at
   (sub)mm wavelengths the majority of these sources become too weak
   and variable to reliably set the flux density scale. Alternatives
   are thermal objects such as planets, moons, and asteroids. Being
   Solar System objects, these objects do not move at the sidereal
   rate and may be (strongly) resolved. The
   *standard=’Butler-JPL-Horizons 2010’* and the recommended
   *standard=’Butler-JPL-Horizons 2012’* (for more information on the
   implemented models, see Flux Calibrator
   Models
   page and also ALMA Memo 594  [1]_.) option of **setjy**
   includes flux density calibration using Solar System objects.

   For ’Butler-JPL-Horizons 2012’ CASA currently supports the objects
   listed in Flux Calibrator
   Models
   to be applied to ALMA data. These names are recognized when they
   are used in the *’field’* parameter in **setjy**. In that case,
   **setjy** will obtain the geocentric distance and angular diameter
   at the time of the observation from a JPL–Horizons ephemeris and
   calculate model visibilities. Currently the objects are modeled as
   uniform temperature disks. Note that this model may oversimplify
   the real structure, in particular asteroids. The supported
   brightness temperature models for Solar System objects can be
   listed by selecting a *standard* and *listmodels=True* without
   setting any other parameters as shown below:

   ::

      setjy(standard=‘Butler-JPL-Horizons 2012’, listmodels=True)

   Each model contains temperatures at tabulated frequencies except
   for Mars. For Mars, the model temperatures are tabulated in time
   and frequency (see Flux Calibrator Models - Conventions, Data
   Formats
   for more details).

   For selected asteroids, time variable models are available based
   on thermophysical modeling by T. Mueller (private communication)
   for January 1st, 2014 and beyond. Currently, the new models are
   available for Ceres, Pallas, and Vesta. A model is also available
   for Lutetia but using this source for ALMA absolute flux
   calibration is not advised. These new models are automatically
   chosen for the data taken after 2014 January 1, 0 hr UT. These
   models are also listed when the **setjy** task is executed with
   *standard=‘Butler-JPL-Horizons 2012’* and *listmodels=True*. These
   model data files contain flux densities tabulated in time and
   frequency (see Flux Calibrator Models - Conventions, Data
   Formats
   for more details).

   Flux density calculation with Solar System objects depends on
   ephemerides. The **setjy** task looks for the data in
   *os.getenv('CASAPATH').split()[0] +
   '/data/ephemerides/JPL-Horizons'*.  If no ephemeris for the right
   object at the right time is present, the calculation will fail.
   Ask the `ALMA helpdesk <https://help.almascience.org/>`__ to make
   an ephemeris. The very adventurous and well versed in python
   can try it using CASA's *recipes.ephemerides* package:

   ::

      import recipes.ephemerides as eph
      help eph

   CASA comes with ephemerides for several more objects, but they are
   intended for use with **me.framecomet()**, and are not
   (yet) suitable flux density calibrators. It is up to the observer
   to pick a good flux density calibrator (bright, spherical and
   featureless, on a circular orbit, in the right part of the
   sky, and not too resolved). Even some of the objects listed
   above may prove to require more sophisticated flux density models
   than are currently implemented in CASA. For many objects
   running **casalog.filter('INFO1')** before running **setjy** will
   send more information to the logger.

   .. warning:: The apparent brightness of objects in the Solar
      System will vary with time because of the Earth’s varying
      distance to these objects, if nothing else. If the field index
      of a flux calibrator spans several days, **setjy** should be
      run more than once, limiting each run to a suitable timerange
      by using the timerange, scan, and/or observation selection
      parameters. Note that it is the field index that matters, not
      the name. Typically concat assigns moving objects a new field
      index for each observation, so usually it is not necessary to
      select a time range in **setjy**. However, it is worth checking
      with ``listobs``, especially for planets.
