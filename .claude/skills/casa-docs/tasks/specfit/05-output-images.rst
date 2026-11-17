   
   .. rubric:: OUTPUT IMAGES
   
   In addition to the returned dictionary, optionally one or more of
   any combination of output images can be written. The *model* and
   *residual* parameters indicate the names of the model and residual
   images to be written; blank values inidcate that these images
   should not be written.
   
   One can also write none, any or all of the solution and error
   images for Gaussian singlet, Lorentzian singlet, and Gaussian
   multiplet fits via the parameters *amp*, *amperr*, *center*,
   *centererr*, *fwhm*, *fwhmerr*, *integral*, and *integralerr* when
   doing multi-pixel fits. These images simply contain the arrays
   described for the associated parameter solutions or errors
   described in previous sections. In the case of Lorentzian
   singlets, "_ls" is appended to the image names, in the case of
   Gaussian multiplets, "_gm" is appended. Pixels for which fits were
   not attempted or did not converge will be masked as bad. The last
   axis of these images is a linear axis and repesents component
   number (and is named accordingly). In the case where multiple
   Gaussian singlets and/or Lorentzians are fitted, the image names
   are further appended with an underscore and the relevant component
   number ("_0", "_1", etc). In the case of Gaussian multiplets, the
   image names are appended with an underscore, followed by the
   number of the relevant multiplet group, followed by an underscore,
   followed by the number of the component in that group (e.g.,
   "image_gm_3_4" represents component number 4 of multiplet group
   number 3). Pixels for which fits were not attempted, did not
   converge, or converged but have values of NaN (not a number) or
   INF (infinity) will be masked as bad.
   
   Writing analogous images for polynomial coefficients is not
   supported.


   Bibliography

   .. [1] [Brouw, Wim, 1999 `Web <http://www.astron.nl/casacore/trunk/casacore/doc/notes/224.html>`__
   
   .. [2] W.H. Press et al 1988., Cambridge University Press
