
   .. rubric:: Task output

   Below is a list of the products produced by the **simobserve**
   task. Not all of these will necessarily be produced, depending on
   input parameters selected.

   .. note:: **NOTE**: To support different runs with different arrays, the
      names have the configuration name from antenna list appended.

   -  [project].[cfg].skymodel = 4D input sky model image
      (optionally) scaled
   -  [project].[cfg].skymodel.flat.regrid.conv = input sky regridded
      to match the output image, and convolved with the output clean
      beam
   -  [project].[cfg].skymodel.png = diagnostic figure of sky model
      with pointings
   -  [project].[cfg].ptg.txt = list of mosaic pointings
   -  [project].[cfg].quick.psf = psf calculated from uv coverage
   -  [project].[cfg].ms = noise-free MeasurementSet
   -  [project].[cfg].fullpol.ms = corrupted MeasurementSet only with polarization leakage (produced in case the *leakage* input parameter was set to a value > 0.) 
   -  [project].[cfg].noisy.ms = MeasurementSet with noise corruptions (in case leakage = 0)
   -  [project].[cfg].noisier.ms = MeasurementSet with noise corruptions and polarization leakage (leakage > 0)
   -  [project].[cfg].observe.png = diagnostic figure of uv coverage
      and visibilities
   -  [project].[cfg].simobserve.last = saved input parameters for
      **simobserve** task


   .. rubric:: Parameter descriptions

   *project*

   The root filename for all output files. This parameter should be
   set to the same name as used when running **simanalyze** or
   **simalma** for the directory of results generated.

   *skymodel*

   The input image (used as a model of the sky). **simobserve** uses
   a CASA or FITS image. If you merely have a grid of numbers, you
   will need to write them out as FITS or write a CASA script to read
   them in and use the **ia** tool to create an image and insert the
   data. **simobserve** does NOT require a coordinate system in the
   header. If the coordinate information is incomplete, missing, or
   you would like to override it, set the appropriate "in"
   parameters.

   .. note:: **NOTE**: Setting those parameters simply changes the header
      values, ignoring any values already in the image. No regridding
      is performed.

   You can also manipulate an image header manually with the
   **imhead** task. If you have a proper Coordinate System,
   **simobserve** will do its best to generate visibilities from
   that.

   .. rubric:: *skymodel* expandable parameters

   *inbright*

   Scales the model flux densities by setting the peak brightness of
   the britest pixel in Jy/pixel, or '' for unchanged.

   .. warning:: **WARNING**: 'unchanged' will take the numerical values in your
      image and assume they are in Jy/pixel, even if it says some
      other unit in the header.

   *indirection*

   The central direction to place the sky model image, or '' to use
   whatever is in the image already.

   *incell*

   The spatial pixel size to scale the skymodel image, or '' to use
   whatever is in the image already.

   *incenter*

   The frequency to use for the center channel (or only channel, if
   the skymodel is 2D). Examples: *incenter='89GHz'*, or '' to use
   what is in the header. This will also become the default rest frequency, e.g. when imaging with tclean.

   *inwidth*

   The width of the channels to use, or '' to use what is in the
   image should be a string representing a quantity with units.
   Examples: *inwidth='10MHz'*

   .. note:: **NOTE**: *inwidth* only works reliably with frequencies, not
      velocities.

   .. note:: **NOTE** **2**: It is not possible to change the number of
      spectral planes of the sky model, only to relabel them with
      different frequencies. That kind of regridding can be
      accomplished with the CASA toolkit.


   *complist*

   A component list model of the sky, added to or instead of
   *skymodel*.

   .. warning:: **WARNING**: **simobserve** does not currently handle component
      lists correctly for single-dish-only simulations. It is advised
      to convert the component list to an image or FITS file.

   .. rubric:: complist expandable parameters

   *compwidth*

   The bandwidth of components; if simulating from components only,
   this defines the bandwidth of the MS and output images.

   *comp_nchan*

   The number of channels in the output MS. Validated only for a
   positive integer number of channels, this parameter assumes a flat
   spectrum and equal spacing when setting the channel width in the
   output MS. Since variation in channel width as a function of
   frequency is not currently supported, it is not advised to use
   this parameter to simulate observations with spectral index or
   large fractional bandwidth (use a skymodel image instead).


   *setpointings*

   If True, **simobserve** calculates a map of pointings based on a
   set of sub-parameters and generates a pointing file. If False, it
   will read the pointings from the parameter *ptgfile*.

   .. rubric:: *setpointings=True* expandable parameters

   *integration*

   Sets the time interval for each integration. Also used with
   *setpointings=False*. Examples: *integration='10s'*

   .. note:: **NOTE**: To simulate a 'scan' longer than one integration, use
      *setpointings* to generate a pointing file, and then edit the
      file to increase the time at each point to be larger than the
      parameter integration time.

   *direction*

   The mosaic center direction. If left unset, **simobserve** will
   use the center of the skymodel image. Examples: *direction= 'J2000
   19h00m00 -40d00m00';* can optionally be a list of pointings,
   otherwise **simobserve** will cover a region of size *mapsize*
   according to *maptype*.

   *mapsize*

   The angular size of mosaic map to simulate. Set to '' to cover the
   model image.

   *maptype*

   How to calculate the pointings for the mosaic observation.
   'hexagonal', 'square' (rectangular raster), 'ALMA' for the same
   hex algorithm as the ALMA Cycle 1 OT or 'ALMA2012' for the
   algorithm used in the Cycle 0 OT.

   *pointingspacing*

   Spacing in between primary beams. "0.25PB" to use 1/4 of the
   primary beam FWHM, "nyquist" will use :math:`\lambda/d/2`, '' will
   use :math:`\lambda/d/\sqrt(3)` for INT, :math:`\lambda/d/3` for
   SD.

   .. rubric:: *setpointings=False* expandable parameters

   *ptgfile*

   A text file specifying directions in the following format, with
   optional integration times, e.g.,

   ::

      #Epoch     RA          DEC      TIME(optional)
      J2000 23h59m28.10 -019d52m12.35 10.0

   If the time column is not present in the file, it will use
   'integration' for all pointings.

   .. note:: **NOTE**: At this time the file should contain only science
      pointings: **simobserve** will observe these, then optionally
      the calibrator, then the list of science pointings again, etc,
      until totaltime is used up.


   *obsmode*

   Sets the observation mode to calculate visibilities from a
   skymodel image (which may have been modified above), an optional
   component list, and a pointing file (which also may have been
   generated above). This parameter takes two possible values:

   -  interferometer (or int)
   -  singledish (or sd)

   If simulating from a component list, you should specify
   *compwidth*, the desired bandwidth. There is not currently a way
   to specify the spectrum of a component, so simulations from a
   componentlist only will be continuum (1 chan).
