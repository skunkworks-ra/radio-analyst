

.. _Returns:

Returns
   results (dict) - fitted parameters and information on fit quality
   and units of the axes, if wantreturn=True


.. _Description:

Description
   specfit task: Fit 1-dimensional gaussians/lorentzians and/or
   polynomial models to an image or image region
   
   Simultaneously performs a non-linear, least squares fit using the
   Levenberg-Marquardt algorithm of one or more Gaussian singlets,
   one or more Lorentzian singlets, one or more Gaussian multiplets,
   and/or a polynomial to one dimensional spectral profiles. A
   description of the fitting algorithm may be found in AIPS++ Note
   224 [1]_ and in Numerical Recipes [2]_ . A
   Gaussian/Lorentzian singlet is a Gaussian/Lorentzian function
   whose parameters (amplitude, center position, and width) are all
   independent from any other parameters that may be simultaneously
   fit. A Gaussian multiplet is a set of two or more Gaussian
   functions in which at least one (and possibly two or three) of the
   parameters of each function depend on the parameters of another,
   single, reference function in the multiplet. For example: one can
   specify a doublet in which the amplitude of the first spectral
   line is 0.6 times the amplitude of the zeroth (reference) spectral
   line, and/or the center of the first line is 20 pixels from the
   center of the zeroth line, and/or the fwhm of the first line is
   identical (in pixels) to that of the zeroth line. There is no
   limit to the number of components one can specify for a multiplet,
   except of course that the number of parameters to be fit should be
   significantly less than the number of data points. There can only
   be a single reference profile in a multiplet, to which the
   parameters of the other component profiles in the multiplet are
   tied to.
   
   .. rubric:: AXIS
   
   The *axis* parameter indicates along which axis the profiles
   should be fit; a negative value indicates that the spectral axis
   should be used, or if one does not exist, that the zeroth axis
   should be used.
   
   .. rubric:: MINIMUM NUMBER OF PIXELS
   
   The *minpts* parameter indicates the minimum number of unmasked
   pixels that must be present in order for a fit to be attempted.
   When *multifit=True*, positions with too few good points will be
   masked in any output images.
   
   .. rubric:: ONE FIT OF REGION AVERAGE OR PIXEL BY PIXEL FIT
   
   The *multifit* parameter indicates if profiles should be fit at
   each pixel position in the selected region (true), or if the
   spectral profiles in that region should be averaged together and
   the fit done to that averaged spectral profile (false).
   
   .. rubric:: POLYNOMIAL FITTING
   
   The order of the polynomial to fit is specified via the *poly*
   parameter. If *poly<0*, no polynomial fit will be attempted. No
   initial estimates of coefficients can be specified; these are
   determined automatically.
   
   .. rubric:: Gaussian SINGLET FITTING
   
   The *ngauss* parameter specifies the maximum number of Gaussian
   singlets to be fitted, if no estimates are specified by the
   profile's initial parameter estimates pampest, pcenterest and
   pfwhmest (the so-called *p\*est* parameters) or by
   an estimates file, and if gmncomps=0 or is empty. The initial
   estimates of the parameters for these Gaussians will be
   determined automatically in this case. If it deems it appropriate,
   the fitter will fit fewer Gaussians than this number.  If
   the *estimates* parameter is not specified, or the *p*est*
   parameters are not specified and *ngauss=0*, *gmncomps* is empty
   or 0, and *poly<0*, an error will occur as this indicates there is
   nothing to fit.
   
   One can specify initial estimates of Gaussian singlet parameters
   via an estimates file or the *pampest*, *pcenterest*, *pfwhmest*,
   and optionally, the *pfix* parameters. The latter is the
   recommended way to specify these estimates as support for
   estimates files may be deprecated in the future. No matter which
   option is used, an amplitude initial estimate must always be
   nonzero. A negative fwhm estimate will be silently changed to
   positve.
   
   .. rubric:: SPECIFYING INITIAL ESTIMATES FOR Gaussian AND
      Lorentzian SINGLETS (RECOMMENDED METHOD)
   
   One may specify initial estimates via the *pampest*, *pcenterest*,
   and *pfwhmest* parameters. In the case of a single Gaussian or
   Lorentzian singlet, these parameters can be scalar numbers.
   *pampest* must be specified in image brightness units,
   *pcenterest* must be given in the number of pixels from the zeroth
   pixel, and *pfwhmest* must be given in pixels. Optionally *pfix*
   can be specified and in the case of a single Gaussian or
   Lorentzian singlet, it can be a string. The string indicates which
   parameters should be held constant during the fit. Any combination
   of "p" (amplitude), "c" (center), or "f" (fwhm) is allowed; e.g.
   *pfix="pc"* means fix both the amplitude and center of a
   Gaussian/Lorentzian profile during the fit. In the case of more
   than one Gaussian and/or Lorentzian singlets, these parameters
   must be specified as arrays of numbers. The length of the arrays
   indicates the number of singlets to fit and the array length must
   be the same for all the *p*est* parameters.
   
   If no parameters are to be fixed for any of the singlets, *pfix*
   can be set to the empty string. However, if at least one parameter
   of one singlet is to be fixed, *pfix* must be an array of strings
   and have a length equal to that of the *p*est* arrays. Singlets
   which are not to have any parameters fixed should be represented
   as an empty string in the *pfix* array. So, for example, if one
   desires to fit three singlets and fix the fwhm of the middle one,
   one must specify *pfix=["", "f", ""]*, the other two empty strings
   indicating that no parameters of the zeroth and second singlet
   should be held constant.
   
   In the case of *multifit=True*, the initial estimates, whether
   from the *p*est* parameters or from a file (see below), will be
   applied to the location of the first fit. This is normally the
   bottom left corner of the region selected. If the region is
   masked, or does not contain enough good points to perform a fit,
   or if the attempted fit fails, the fitting proceeds to the next
   pixel, with the pixel value of the lowest numbered axis changing
   the fastest. Once a successful fit has been performed, subsequent
   fits will use the results of the fit of a nearest pixel, for which
   a previous fit was successful, as the initial estimates for the
   parameters at the current location. The fixed parameter string
   *pfix* will be honored for every fit performed when
   *multifit=True*.
   
   One specifies what type of PCF profile to fit via the *pfunc*
   parameter. A PCF function is one that can be parameterized by a
   peak, center, and FWHM, as both Gaussian and Lorentzian singlets
   can. If all singlets to be fit are Gaussians, one can set *pfunc*
   equal to the empty string and all snglets will be assumed to be
   Gaussians. If at least one Lorentzian is to be fit, *pfunc* must
   be specified as a string (in the case of a single singlet) or an
   array of strings (in the case of multiple singlets). The position
   of each string corresponds to the positions of the initial
   estimates in the *p*est* and *pfix* arrays. Minimal match ("g",
   "G", "l", or "L") is supported. So, if one wanted to
   simultaneously fit two Gaussian and two Lorentzian singlets, the
   zeroth and last of which were Lorentzians, one would specify
   *pfunc=["L", "G", "G", "L"]*.
