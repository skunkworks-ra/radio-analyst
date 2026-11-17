

.. _Returns:

Returns
   out (dict) - fitting information including list of fitted
   components, per-channel convergence, and direction coordinate pixel
   increments


.. _Description:

Description
   This task is used to fit one or more two dimensional
   Gaussians to sources in an image as well as an optional zero-level
   offset. Fitting is limited to a single polarization but can be
   performed over several contiguous spectral channels. If the image
   has a clean beam, the report and returned dictionary will contain
   both the convolved and the deconvolved fit results. For examples
   and explanation of the dictionary, see the Image Plane
   Analysis
   pages.

   When dooff is False, the method returns a dictionary with keys
   named 'converged', 'pixelsperarcsec', 'results', and
   'deconvolved'. The value of 'converged' is a boolean array which
   indicates if the fit converged on a channel by channel basis. The
   value of 'pixelsperarcsec' is a two element double array with the
   absolute values of the direction coordinate pixel increments
   (longitude-like and latitude-like coordinate, respectively) in
   arcsec. The value of 'results' is a dictionary representing a
   component list reflecting the fit results. In the case of an image
   containing beam information, the sizes and position angles in the
   'results' dictionary are those of the source(s) convolved with the
   restoring beam, while the same parameters in the 'deconvolved'
   dictionary represent the source sizes deconvolved from the beam.
   In the case where the image does not contain a beam, 'deconvolved'
   will be absent. Both the 'results' and 'deconvolved' dictionaries
   can be read into a component list tool (default tool is named cl)
   using the fromrecord() method for easier inspection using tool
   methods, eg
   
   ::
   
      cl.fromrecord(res['results'])
   

   although this only works if the flux density units are conformant
   with Jy.
   
   There are also values in each component subdictionary not used by
   **cl.fromrecord()** but meant to supply additional information.
   There is a 'peak' subdictionary for each component that provides
   the peak intensity of the component. It is present for both
   'results' and 'deconvolved' components. There is also a 'sum'
   subdictionary for each component indicating the simple sum of
   pixel values in the the original image enclosed by the fitted
   ellipse. There is a 'channel' entry in the 'spectrum'
   subdictionary which provides the zero-based channel number in the
   input image for which the solution applies. In addtion, if the
   image has a beam(s), then there will be a 'beam' subdictionary
   associated with each component in both the 'results' and
   'deconvolved' dictionaries. This subdictionary will have three
   keys: '*beamarcsec*' will be a subdictionary giving the beam
   dimensions in arcsec, '*beampixels*' will have the value of the
   beam area expressed in pixels, and '*beamster*' will have the
   value of the beam area expressed in steradians. Also, if the image
   has a beam(s), in the component level dictionaries will be an
   'ispoint' entry with an associated boolean value describing if the
   component is consistent with a point source. Each component level
   dictionary will have a 'pixelcoords' entry which has the value of
   a two element numeric array which provides the direction pixel
   coordinates of the fitted position.
   
   If *dooff* is True, in addition to the specified number of
   Gaussians, a zero level offset will also be fit. The initial
   estimate for this offset is specified using the *offset*
   parameter. Units are assumed to be the same as the image
   brightness units. The zero level offset can be held constant
   during the fit by specifying *fixoffset=True*. In the case of
   *dooff=True*, the returned dictionary contains two additional
   keys, '*zerooff*' and '*zeroofferr*', which are both dictionaries
   containing '*unit*' and '*value*' keys. The values associated with
   the '*value*' keys are arrays containing the fitted zero level
   offset value and its error, respectively, for each channel. In
   cases where the fit did not converge, these values are set to NaN.
   The value associated with '*unit*' is just the image brightness
   unit.
   
   The region can either be specified by a *box(es)* or a *region*.
   Ranges of pixel values can be included or excluded from the fit.
   If specified using the *box* parameter, multiple boxes can be
   given using the format *box* ="blcx1, blcy1, trcx1, trcy1, blcx2,
   blcy2, trcx2, trcy2, ... , blcxN, blcyN, trcxN, trcyN" where N is
   the number of boxes. In this case, the union of the specified
   boxes will be used.
   
   The default behavior of imfit is to fit a single Gaussian
   component. If a multiple-Gaussian fit is desired, the user must
   specify initial estimates via a text file (see below for details).
   If no estimate file is specified, imfit will attempt to guess the
   initial parameters and fit a single Gaussian to the union of
   specified boxes/regions. Users who wish to perform individual fits
   to separate regions should run imfit multiple times, specifying a
   single input box/region each time.
   
   If specified, the *residual* and/or *model* images for successful
   fits will be written.
   
   The user has the option of writing the result of the fit to a log
   file, and has the option of either appending to or overwriting an
   existing file.
   
   The user has the option of writing the (convolved) parameters of a
   successful fit to a file which can be fed back to **imfit** as the
   new estimates file for a subsequent run.
   
   The user has the option of writing the fit results in tabular
   format to a file whose name is specified using the *summary*
   parameter.
   
   If specified and positive, the value of *rms* is used to calculate
   the parameter uncertainties, otherwise, the rms in the selected
   region in the relevant channel is used for these calculations.
   
   The *noisefwhm* parameter represents the noise-correlation beam
   FWHM. If specified as a quantity, it should have angular units. If
   specified as a numerical value, it is set equal to that number of
   pixels. If specified and greater than or equal to the pixel size,
   it is used to calculate parameter uncertainties using the
   correlated noise equations (see below). If it is specified but
   less than a pixel width, the uncorrelated noise equations (see
   below) are used to compute the parameter uncertainties. If it is
   not specified and the image has a restoring beam(s), the
   correlated noise equations are used to compute parameter
   uncertainties using the geometric mean of the relevant beam major
   and minor axes as the noise-correlation beam FWHM. If *noisefwhm*
   is not specified and the image does not have a restoring beam,
   then the uncorrelated noise equations are used to compute the
   parameter uncertainties.
