

.. _Description:

Description
   .. warning:: **Note**: **specflux** is currently an experimental task.
   
   **specflux** retrieves details of a multi-channel image spectrum
   which has been integrated over a given region (or the entire image
   by default). One may specify which function to use to combine the
   pixel values within the region using the *function* parameter.
   Supported values are 'flux density', 'mean', 'median', and 'sum'.
   Minimal match is supported. **specflux** also calculates
   spectrally integrated flux (brightness) values. 
   
   The task uses the brightness units that are specified in the image
   header (e.g., Jy/beam or K). When 'flux density' is calculated,
   the resulting spectra are in units of Jy for cube units of Jy/beam
   and :math:`K*arcsec^2` for cube units of K. 
   
   The spectral integral that **specflux** calculates is the sum of
   the spectrum multiplied by the channel width. The units are
   updated accordingly. 
   
   If the units are :math:`K*arcsec^2`, multiply the reported value
   by :math:`2.3504\times10^{-8}\times d^2`, where :math:`d` is in
   pc, to convert from units of :math:`K*arcsec^2` to units of
   :math:`K*pc^2`.
   
   If provided, *major* and *minor* will be used to compute the beam
   size, and hence the per channel flux densities (if *function="flux
   density"*), overriding the input image beam information (if
   present).
   
   .. note:: **NOTE**: When it is not possible to compute the spectral flux
      (e.g., in the case where the brightness units are Jy/beam but
      the image has no synthesized beam and none is provided to the
      task), then the application will fail.
   
   The output of **specflux** is written to the CASA logger and an
   ASCII file if *logfile* is specified.
   
   .. rubric:: Parameter descriptions
   
   *imagename*
   
   Name of the input image (CASA, FITS or MIRIAD images are
   accepted). 
   
   *region*
   
   Region selection, using a CASA region
   file.
   Default is the entire image. 
   
   *box*
   
   Rectangular spatial
   selection,
   if no region file is supplied. Default is the entire image.
   
   *chans*
   
   Spectral/channel
   selection,
   if no region file is supplied. Default is the entire channel
   range. 
   
   *stokes*
   
   Stokes
   selection,
   if no region file is supplied. Default are all Stokes planes. 
   
   *mask*
   
   An image
   mask
   file. Default is not to use a mask.  
   
   *stretch*
   
   If the image mask is a single plane and not a cube of the same
   dimension as the input data cube, *stretch* can by set to True to
   extend the mask to all planes. (Default: False)
   
   *function*
   
   Aggregate function to use for computing per channel values.
   Supported values are 'flux density', 'mean', 'median', 'sum'.
   Minimal match is supported.
   
   *unit*
   
   Unit to use for the spectral flux calculation. Must be conformant
   with a typical spectral axis unit. Velocity units may only be used
   if the spectral coordinate has a rest frequency and if it is
   :math:`> 0`.
   
   *major*
   
   Major axis of overriding restoring beam. If specified, it must be
   a valid quantity (e.g., "4arcsec").
   
   *minor*
   
   Minor axis of overriding restoring beam. If specified, it must be
   a valid quantity (e.g., "3arcsec").
   
   *logfile*
   
   File which to write details. Default is to not write to a file.
   
   *overwrite*
   
   Overwrite exisitng *logfile* file if it exists. (Default: False)
