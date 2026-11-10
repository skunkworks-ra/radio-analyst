   
   .. rubric:: LIMITING RANGES FOR SOLUTION PARAMETERS
   
   In cases of low (or no) signal to noise spectra, it is still
   possible for the fit to converge, but often to a nonsensical
   solution. The astronomer can use her knowledge of the source to
   filter out obviously spurious solutions. Any solution which
   contains a NaN value as a value or error in any one of its
   parameters is automatically marked as invalid.
   
   One can also limit the ranges of solution parameters to known
   "good" values via the goodamprange, goodcenterrange, and
   goodfwhmrange parameters. Any combination can be specified and the
   limit constraints will be ANDed together. The ranges apply to all
   PCF components that might be fit; choosing ranges on a component
   by component basis is not supported. If specified, an array of
   exactly two numerical values must be given to indicate the range
   of acceptable solution values for that parameter. *goodamprange*
   is expressed in terms of image brightness units. *goodcenterrange*
   is expressed in terms of pixels from the zeroth pixel in the
   specified region. *goodfwhmrange* is expressed in terms of pixels
   (only non-negative values should be given for FWHM range
   endpoints). In the case of a multiple-PCF fit, if any of the
   corresponding solutions are outside the specified ranges, the
   entire solution is considered to be invalid.
   
   In addition, solutions for which the absolute value of the ratio
   of the amplitude error to the amplitude exceeds 100 or the ratio
   of the FWHM error to the FWHM exceeds 100 are automatically marked
   as invalid.
   
   .. rubric:: INCLUDING STANDARD DEVIATIONS OF PIXEL VALUES
   
   If the standard deviations of the pixel values in the input image
   are known and they vary in the image (e.g. they are higher for
   pixels near the edge of the band), they can be included in the
   *sigma* parameter. This parameter takes either an array or an
   image name. The array or image must have one of three shapes:
   
   #. the shape of the input image,
   #. the same dimensions as the input image with the lengths of all
      axes being one except for the fit axis which must have length
      corresponding to its length in the input image, or
   #. be one dimensional with length equal the the length of the fit
      axis in the input image.
   
   In cases 2 and 3, the array or pixels in sigma will be replicated
   such that the image that is ultimately used is the same shape as
   the input image. The values of sigma must be non-negative. It is
   only the relative values that are important. A value of 0 means
   that pixel should not be used in the fit. Other than that, if
   pixel A has a higher standard deviation than pixel B, then pixel A
   is noisier than pixel B and will receive a lower weight when the
   fit is done. The weight of a pixel is the usual:
   
   weight = :math:`\frac{1}{\sigma^2}`
   
   In the case of *multifit=F*, the sigma values at each pixel along
   the fit axis in the hyperplane perpendicular to the fit axis which
   includes that pixel are averaged and the resultant averaged
   standard deviation spectrum is the one used in the fit.
   Internally, sigma values are normalized such that the maximum
   value is 1. This mitigates a known overflow issue.
   
   One can write the normalized standard deviation image used in the
   fit but specifying its name in *outsigma*. This image can then be
   used as *sigma* for subsequent runs.
   
   .. rubric:: RETURNED DICTIONARY STRUCTURE
   
   The dictionary returned (if *wantreturn=True*) has a (necessarily)
   complex structure. First, there are keys "xUnit" and "yUnit" whose
   values are the abscissa unit and the ordinate unit described by
   simple strings. Next there are arrays giving a broad overview of
   the fit quality. These arrays have the shape of the specified
   region collapsed along the fit axis with the axis corresponding to
   the fit axis having length of 1:
   
   -  ATTEMPTED: a boolean array indicating which fits were attempted
      (e.g. if too few unmasked points, a fit will not be attempted)
   -  CONVERGED: a boolean array indicating which fits converged.
      False if the fit was not attempted
   -  VALID: a boolean array indicating which solutions fall within
      the specified valid ranges of parameter space (see section
      **LIMITING RANGES FOR SOLUTION PARAMETERS** for details)
   -  NITER: an int array indicating the number of iterations for
      each profile, a negative value indicates the fit did not
      converge
   -  NCOMPS: the number of components (Gaussian singlets +
      Lorentzian singlets + Gaussian multiplets + polynomial) fit for
      the profile, a negative value indicates the fit did not
      converge
   -  DIRECTION: a string array containing the world direction
      coordinate for each profile
   
   There is a "type" array having number of dimensions equal to the
   number of dimensions in the above arrays plus one. The shape of
   the first n-1 dimensions is the same as the shape of the above
   arrays. The length of the last dimension is equal to the number of
   components fit. The values of this array are strings describing
   the components that were fit at each position ("POLYNOMIAL",
   "Gaussian" in the case of Gaussian singlets, "Lorentzian" in the
   case of Lorentzian singlets, and ""Gaussian MULTPLET").
   
   If any Gaussian singlets were fit, there will be a subdictionary
   accessible via the "gs" key which will have subkeys "amp",
   "ampErr", "center", "centerErr", "fwhm", "fwhmErr, "integral", and
   "integralErr". Each of these arrays will have one more dimension
   than the overview arrays described above. The shape of the first
   n-1 dimensions will be the same as the shape of the arrays
   described above, while the final dimension will have length equal
   to the maximum number of Gaussian singlets that were fit. Along
   this axis will be the corresponding fit result or associated error
   (depending on the array's associated key) of the fit for that
   singlet component number. In cases where the fit did not converge,
   or that particular component was excluded from the fit, a value of
   NAN will be present.
   
   If any Lorentzian singlets were fit, their solutions will be
   accessible via the "ls" key. These arrays follow the same rules as
   the "gs" arrays described above.
   
   If any Gaussian multiplets were fit, there will be subdictionaries
   accessible by keys "gm0", "gm1", ..., "gm{n-1}" where n is the
   number of Gaussian muliplets that were fit. Each of these
   dictionaries will have the same arrays described above for
   Gaussian singlets. The last dimension will have length equal to
   the number of components in that particular multiplet. Each pixel
   along the last axis will be the parameter solution value or error
   for that component number in the multiplet, e.g. the zeroth pixel
   along that axis contains the parameter solution or error for the
   reference component of the multiplet.
   
   The polynomial coefficient solutions and errors are not returned,
   although they are logged.
