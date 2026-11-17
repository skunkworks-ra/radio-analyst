

   .. rubric:: NOTES ON FLUX DENSITIES AND FLUXES

   .. note:: Explanation of terminology:

      The terms "intensity" or "brightness" refer to quantities
      with a unit such as Jy/beam or Kelvin (K).

      The term "flux density" refers to quantities with a unit such
      as Janskys (Jy). This is dimensionally equivalent to
      W/m**2/Hz.

      The term "flux" refers to a flux density integrated over the
      spectral or velocity axis, such as Jy*km/s or Jy*Hz. These
      are dimensionally equivalent to W/m**2.

   Fluxes and flux densities are not computed if any of the following
   conditions is met:

   #. The image does not have a direction coordinate
   #. The image does not have a intensity-like brightness unit.
      Examples of such units are Jy/beam (in which case the image
      must also have a beam) and Kelvin (K)
   #. There are no direction axes in the cursor axes that are used
   #. If the (specified region of the) image has a non-degenerate
      spectral axis, and the image has a tabular spectral axis (axis
      with varying increments) [a]
   #. Any axis that is not a direction nor a spectral axis that is
      included in the cursor axes is not degenerate within in
      specified region

   In cases where none of the above conditions is met, the flux
   density(ies) (intensities integrated over direction planes) will
   be computed if any of the following conditions is met:

   #. The image has no spectral coordinate
   #. The cursor axes do not include the spectral axis
   #. The spectral axis in the chosen region is degenerate

   In the case where there is a non-degenerate spectral axis that is
   included in the cursor axes, the flux (flux density integrated
   over spectral planes) will be computed. In this case, the spectral
   portion of the flux unit will be the velocity unit of the spectral
   coordinate if it has one (e.g., if the brightness unit is Jy/beam
   and the velocity unit is km/s, the flux will have units of Jy
   km/s). If not, the spectral portion of the flux unit will be the
   frequency unit of the spectral axis (e.g., if the brightness unit
   is K and the frequency unit is Hz, the resulting flux unit will be
   K arcsec :sup:`2` Hz).

   In both cases of flux density or flux being computed, the
   resulting numerical value is assigned to the "flux" key in the
   output dictionary.

   If the image has units of Jy/beam, the flux density is just the
   mean intensity multiplied by the number of beam areas included in
   the region. The beam area is defined as the volume of the
   elliptical Gaussian defined by the synthesized beam, divided by
   the maximum of that function, which is equivalent to

   :math:`\frac {π}{4 ln(2)} * FWHM_{major} * FWHM_{minor}`

   where ln() is the natural logarithm and :math:`FWHM_{major}` and
   :math:`FWHM_{minor}` are the major and minor full width at half
   maximum (FWHM) axes of the beam, respectively.


   .. rubric:: Task-specific Parameters Summary

   *axes*

   Cursor axes over which to evaluate statistics.

   *listit*

   Print stats and bounding box to logger?

   *verbose*

   Print additional, possibly useful, messages to logger?

   *logfile*

   Name of file to write statistic results.

   *append*

   If logfile exists, append to it if True or overwrite it if False.

   *algorithm*

   Algorithm to use. Supported values are "biweight", "chauvenet",
   "classic", "fit-half", and "hinges-fences". Minimum match is
   supported.

   *fence*

   Fence value for hinges-fences. A negative value means use the
   entire data set (ie default to the "classic" algorithm). Ignored
   if algorithm is not "hinges-fences".

   *center*

   Center to use for fit-half. Valid choices are "mean", "median",
   and "zero". Ignored if algorithm is not "fit-half".

   *lside*

   For fit-half, use values <= center for real data if True? If
   False, use values >= center as real data. Ignored if algorithm is
   not "fit-half".

   *zscore*

   For chauvenet, this is the target maximum number of standard
   deviations data may have to be included. If negative, use
   Chauvenet's criterion. Ignored if algorithm is not "chauvenet".

   *maxiter*

   For chauvenet, this is the maximum number of iterations to
   attempt. Iterating will stop when either this limit is reached, or
   the zscore criterion is met. If negative, iterate until the zscore
   criterion is met. Ignored if algorithm is not "chauvenet".

   *clmethod*

   Method to use for calculating classical statistics. Supported
   methods are "auto", "tiled", and "framework". Ignored if algorithm
   is not "classic".

   *niter*

   For biweight, this is the maximum number of iterations to attempt.
   Iterating will stop when either this limit is reached, or the
   convergence criterion is met. If negative, do a fast, simple
   computation (see description). Ignored if the algorithm is not
   "biweight".


   .. rubric:: Bibliography

   .. [1] Beers, T., Flynn, K., and Gebhardt, K. 1990. AJ, 100, 1, 32.

   .. [2] Iglewicz, Boris. 1983. “Robust Scale Estimators and
      Confidence Intervals for Location” in Understanding Robust and
      Exploratory Data Analysis, eds. Hoaglin, David; Mosteller,
      Frederick; and Tukey, John W., John Wiley and Sons,
      Inc.
