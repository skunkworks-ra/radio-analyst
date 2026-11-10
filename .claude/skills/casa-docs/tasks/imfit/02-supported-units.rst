   
   .. rubric:: SUPPORTED UNITS
   
   Currently only images with brightness units conformant with
   Jy/beam, Jy/beam km/s, and K are fully supported for fitting. If
   your image has some other base brightness unit, that unit will be
   assumed to be equivalent to Jy/pixel and results will be
   calculated accordingly. In particular, the flux density (reported
   as Integrated Flux in the logger and associated with the "flux"
   key in the returned component subdictionary(ies)) for such a case
   represents the sum of pixel values.
   
   Note also that converting the returned results subdictionary to a
   component list via **cl.fromrecord()** currently only works
   properly if the flux density units in the results dictionary are
   conformant with Jy. If you need to be able to run
   **cl.fromrecord()** on the resulting dictionary you can first
   modify the flux density units by hand to be (some prefix)Jy and
   then run cl.fromrecord() on that dictionary, bearing in mind your
   unit conversion.
   
   If the input image has units of K, the flux density of components
   will be reported in units of [prefix]K*rad*rad, where prefix is an
   SI prefix used so that the numerical value is between 1 and 1000.
   To convert to units of K*beam, determine the area of the
   appropriate beam, which is given by
   
   .. math:: \begin{equation} \frac{\pi}{4 \rm{ln} 2} \, b_{\rm maj} \,b_{\rm min} \end{equation}
   
   where :math: `b_{\rm maj}` and :math:`b_{\rm min}` are the major
   and minor axes of the beam, and convert to steradians (=rad*rad).
   This value is included in the beam portion of the component
   subdictionary (key '*beamster*'). Then divide the numerical value
   of the logged flux density by the beam area in steradians. So, for
   example
   
   ::
   
      # run on an image with K brightness units
      res = imfit(...)
      # get the I flux density in K*beam of component 0
      comp = res['results']['component0']
      flux_density_kbeam = comp['flux']['value'][0]/comp['beam']['beamster']
   
    
   
   .. rubric:: FITTING OVER MULTIPLE CHANNELS
   
   For fitting over multiple channels, the result of the previous
   successful fit is used as the estimate for the next channel. The
   number of Gaussians fit cannot be varied on a channel by channel
   basis. Thus the variation of source structure should be reasonably
   smooth in frequency to produce reliable fit results.
   
   .. rubric:: MASK SPECIFICATION
   
   Mask
   specification can be done using an LEL
   expression.
   For example
   
   ::
   
      mask = "myimage>5"
   
   will use only pixels with values greater than 5.
   
   .. rubric:: INCLUDING AND EXCLUDING PIXELS
   
   Pixels can be included or excluded from the fit based on their
   values using these parameters. Note that specifying both is not
   permitted and will cause an error. If specified, both take an
   array of two numeric values.
   
   .. rubric:: ESTIMATES
   
   Initial estimates of fit parameters (peak intensity, peak x pixel
   coordinate, peak y pixel coordinate, major axis, minor axis,
   position angle) may be specified via an estimates text file. Each
   line of this file should contain a set of parameters for a single
   Gaussian. Optionally, some of these parameters can be fixed during
   the fit. The format of each line is: peak intensity, peak x-pixel
   value, peak y-pixel value, major axis, minor axis, position angle,
   fixed.
   
   The fixed parameter is optional. The peak intensity is assumed
   to be in the same units as the image pixel values (eg Jy/beam).
   The peak coordinates are specified in pixel coordinates. The
   major and minor axes and the position angle are the convolved
   parameters if the image has been convolved with a clean beam and
   are specified as quantities. The fixed parameter is optional and
   is a string. It may contain any combination of the following
   characters 'f' (peak intensity), 'x' (peak x position), 'y'
   (peak y position), 'a' (major axis), 'b' (axial ratio, R =
   (major axis FWHM)/(minor axis FWHM)), 'p' (position angle).

   **NOTE: One cannot hold the minor axis fixed without holding the
   major axis fixed.** If the major axis is not fixed, specifying
   'b' in the fixed string will hold the axial ratio fixed during
   the fit.
   
   In addition, lines in the file starting with a # are considered
   comments.
   
   An example of such a file is:
   
   ::
   
      # peak intensity must be in map units
      120, 150, 110, 23.5arcsec, 18.9arcsec, 120deg
      90, 60, 200, 46arcsec, 23arcsec, 140deg, fxp
   
   This is a file which specifies that two Gaussians are to be
   simultaneously fit, and for the second Gaussian the specified peak
   intensity, x position, and position angle are to be held fixed
   during the fit.
