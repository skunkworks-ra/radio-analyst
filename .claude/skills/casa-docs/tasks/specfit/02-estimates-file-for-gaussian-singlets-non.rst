   
   .. rubric:: ESTIMATES FILE FOR Gaussian SINGLETS (NONRECOMMENDED METHOD)

   Initial estimates for Gaussian singlets can be specified in an
   estimates file via the *estimates* parameter, which contains the
   name of the file. Estimates files may be deprecated in the future
   in favor of the *p*est* parameters, so it is recommended users use
   those parameters instead. To use an estimates file, the *p*est*
   parameters must be 0 or empty and *mgncomps* must be 0 or empty.
   Only Gaussian singlets can be specified in an estimates file. If
   one desires to fit one or more Gaussian multiplets and/or one or
   more Lorentzian singlets simultaneously, the *p*est* parameters
   must be used to specify the initial parameters of all Gaussian
   singlets to fit; one cannot use an estimates file in this case. If
   an estimates file is specified, a polynomial can be fit
   simultaneously by specifying the *poly* parameter. The estimates
   file must contain initial estimates of parameters for all Gaussian
   singlets to be fit. The number of Gaussian singlets to fit is
   given by the number of estimate input lines in the file. The file
   can contain comments which are indicated by a "#" at the beginning
   of a line. All non-comment lines will be interpreted as initial
   estimates. The format of such a line is:
   
   [peak intensity], [center], [fwhm], [optional fixed parameter
   string]
   
   The first three values are required and must be numerical values.
   The peak intensity must be expressed in image brightness units,
   while the center must be specified in pixels offset from the
   zeroth pixel, and fwhm must be specified in pixels. The fourth
   value is a character string and it is optional. If present, it
   represents the parameter(s) that should be held constant during
   the fit. Any combination of the characters 'p' (peak), 'c'
   (center), and 'f' (fwhm) are permitted, e.g. "fc" means hold the
   fwhm and the center constant during the fit. Fixed parameters will
   have no errors associated with them. Here is an example file:
   
   ::
   
      # estimates file indicating that two Gaussians should be fit
      # first Gaussian estimate, peak=40, center at pixel number
      #  10.5, fwhm = 5.8 pixels, all parameters allowed to vary during
      # fit 40, 10.5, 5.8

      # second Gaussian, peak = 4, center at pixel number 90.2,
      # fwhm = 7.2 pixels, hold fwhm constant 4, 90.2, 7.2, f
      # end file
