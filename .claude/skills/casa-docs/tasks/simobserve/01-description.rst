

.. _Description:

Description
   .. warning:: There are Known Issues for simobserve.

   This task simulates interferometric or total power
   MeasurementSets. The general steps for simulation in CASA are
   described on the top
   Simulation
   page. We describe the first two steps in more detail here.

   #. Make a model image or componentlist representation of the sky
      brightness distribution.
   #. Use the **simobserve** task to create a MeasurementSet (uv
      data).

   .. rubric:: Generating a Model Image

   A "model image" is a CASA image or FITS file that contains a
   representation of the sky brightness distribution, and it
   represents the object to be "observed" in the simulation. There
   are several ways to generate a model image.

   .. rubric:: Starting from an existing FITS image

   The simplest option is to begin with an existing FITS image. The
   image can be either a single plane (i.e., one observed frequency
   channel) or a cube. A common simulation exercise is to begin with
   a FITS file representing an observation of a target, then scale
   the spatial axes and the flux to shift the data to what would be
   observed for a similar target at a different distance. The
   **simobserve** task has parameters to set the peak flux density,
   coordinates on the sky, pixel size, frequency of the center
   channel, and channel width.

   .. rubric:: Starting from a component list

   .. warning:: **WARNING**: **simobserve** does not currently handle component
      lists correctly for single-dish-only simulations. It is advised
      to convert the component list to an image or FITS file.

   It may be useful to simulate observations of an idealized model
   image consisting, for example, of point sources and Gaussians. The
   CASA component list tool (**cl**) allows the user to specify a set
   of point sources, Gaussians, and disks. One
   can then either use that component list directly
   in **simobserve**, or create a CASA image from the components, or
   both. Details can be found in the Simulations `CASA
   guide <http://casaguides.nrao.edu>`__ entitled 'Simulation Guide Component Lists'.

   .. rubric:: Starting from a GIF or JPG image

   A user may wish to convert a GIF or JPG image to a FITS file for
   simulation in CASA. The image should be converted to a 32-bit FITS
   image for use with the CASA sim tools. Alternatively, you could use ImageMagik from the command
   line, like so:

   ::

      convert myfile.jpg myfile.fits

   Then proceed to trim and convert the file in CASA like so:

   ::

      importfits(fitsimage='myfile.fits',imagename='testimage',overwrite=T)

      default 'immath'
      imagename = 'testimage'
      expr = 'IM0'
      box = '0,0,299,299'
      outfile = 'testimage2'
      immath()

   You can use **imhead** to modify the header parameters of the new
   image, or you can use the parameters in the **simobserve** task to
   modify the peak flux density, coordinates on the sky, pixel size,
   frequency of the center channel, and channel width. See the
   discussion below.


   .. rubric:: Generating visibilities with simobserve

   The task **simobserve** takes several steps to generate observed
   visibilities. The major steps are:

   -  Modify Model: If desired, you can modify the header parameters
      in your data model to mimic different observing targets. For
      example, if you start with a model of M100 you might wish to
      scale the axes to simulate an observation of an M100-like
      galaxy that is 4X more distant.
   -  If the model image has a Stokes axis and provides all four 
      Stokes parameters (I,Q,U,V), then the simulation will be done 
      including the cross-hands and the output image will also be full-Stokes.
      See also the "leakage" parameter.
   -  Set Pointings: If the angular size of your model image is
      comparable or larger than the 12-m primary beam, you can
      simulate observing the target as a mosaic. In this step, the
      individual pointings are determined and saved in a text file.
      You can also generate such a text file yourself.
   -  Generate visibilities: The visibilities are determined based on
      the telescope and configuration specified, and the length in
      time of the observation.
   -  Finally, noise can be added to the visibilities. The
      **simobserve** task uses the
      `aatm <http://www.mrao.cam.ac.uk/%7Ebn204/alma/atmomodel.html>`__
      atmospheric model (based on Juan Pardo's
      `ATM <http://cab.inta-csic.es/users/jrpardo/class_atm.html>`__
      library) to simulate real observing conditions. It can corrupt
      the data with thermal noise and atmospheric attenuation.
      Corruption with an atmospheric phase screen, or adding gain
      fluctuations or drift, can be added subsequently using the
      **simulator** tool **sm** as described in the Simulations `CASA
      Guide <https://casaguides.nrao.edu>`__ entitled 'Corrupting Simulated Data (Simulator Tool)'.

   For details, please see the descriptions of the individual
   parameters below.

   .. warning:: **WARNING**: It is currently not possible to generate a MS in a
      frame other than J2000 e.g., if you set *indirection* to "ICRS
      19h00m00 -40d00m00" it will silently assume that to actually be
      "J2000 19h00m00 -40d00m00". The reference frame can be set to
      ICRS during the imaging or **simanalyze** process.

   .. warning:: **WARNING**: when using a simulated MS in **tclean**, it should
      be considered best practice to declare the *phasecenter*
      parameter using the 'J2000 xx:xx:xx.xxx +xxx.xx.xx.xxx'
      notation to account for possible rounding errors that can
      create an offset in the simulated image.

   .. note:: **NOTE**: **simobserve** calls **sm.predict** with
      **sm.setvp** (*dovp=True*). This means that the vpmanager will
      be queried, and a primary beam pattern will be applied,
      according to the telescope name. One can set the primary beam
      for the given telescope using the **vpmanager**. In most
      circumstances, **simobserve** will use synthesis gridding
      (image-plane primary beam application), unless 1) there are
      more than 1 pointing, AND 2) there are more than one antenna
      diameter in the configuration file. In that case it will
      **sm.setoptions** (*ftmachine="mosaic"*) which enables
      heterogenous array simulation for ALMA, ACA, and OVRO
      telescopes.

      Treatment of the primary beam depends critically on parameters
      set in sm.setvp() and sm.setoptions(ftmachine) - see help
      sm.setvp for details. For componentlists, if sm.setvp() is run
      prior to predict, then the spectral variation of each component
      in the componentlist will include the multiplicative term of
      the beam value for each channel frequency. So a flat spectrum
      component will show the frequency variation of the beam in the
      predicted visibilities.
