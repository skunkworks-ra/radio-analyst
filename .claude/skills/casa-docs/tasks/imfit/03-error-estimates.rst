   
   .. rubric:: ERROR ESTIMATES
   
   Error estimates are based on the work of  Condon (1997)  [1]_
   
   Key assumptions made are:
   
   -  The given model (elliptical Gaussian, or elliptical Gaussian
      plus constant offset) is an adequate representation of the data
   -  An accurate estimate of the pixel noise is provided or can be
      derived (see above). For the case of correlated noise (e.g., a
      CLEAN map), the fit region should contain many "beams" or an
      independent value of rms should be provided.
   -  The signal-to-noise ratio (SNR) of the Gaussian component is
      large. This is necessary because a Taylor series is used to
      linearize the problem. Condon (1997) states that the fractional
      bias in the fitted amplitude due to this assumption is of order
      1/S :sup:`2`, where S is the overall SNR of the Gaussian with
      respect to the given data set (defined more precisely below).
      For a 5 sigma "detection" of the Gaussian, this is a 4% effect.
   -  All (or practically all) of the flux in the component being fit
      falls within the selected region.
   
   If a constant offset term is simultaneously fit and not fixed, the
   region of interest should be even larger. The derivations of the
   expressions summarized in this note assume an effectively infinite
   region.
   
   Two sets of equations are used to calculate the parameter
   uncertainties, based on if the noise is correlated or
   uncorrelated. The rules governing which set of equations are used
   have been described above in the description of the *noisefwhm*
   parameter.
   
   In the case of uncorrelated noise, the equations used are
   
   .. math:: \begin{equation} \frac{\sigma(A)}{A} = \frac{\sigma(I)}{I} = \frac{\sigma(\theta_M)}{\theta_M} = \frac{\sigma(\theta_m)}{\theta_m} = \sqrt{8ln2} \frac{\sigma(x_0)}{\theta_M} = \sqrt{8ln2}\frac{\sigma(y_0)}{\theta_m} = \frac{\sigma(\phi)}{\sqrt{2}}(\frac{\theta_M^2-\theta_m^2}{\theta_M\theta_m}) = \frac{\sqrt{2}}{\rho}\end{equation}
   
   where :math:`\sigma(z)` is the uncertainty associated with
   parameter :math:`z`, :math:`A` is the peak intensity, :math:`I` is
   the flux density, :math:`\theta_M` and :math:`\theta_m` are the
   FWHM major and minor axes, :math:`\phi` is the position angle of
   the component, :math:`x_0` and :math:`y_0` are the direction
   uncertainties of the component measured along the major and minor
   axes; the resulting uncertainties measured along the principle
   axes of the image direction coordinate are calculated by
   propagation of errors using the 2D rotation matrix which enacts
   the rotation through the position angle plus 90 degrees.
   :math:`\rho` is the overall signal to noise ratio of the
   component, which, for the uncorrelated noise case, is given by
   
   .. math:: \begin{equation} \rho = \frac{A}{h\mu}\sqrt{\frac{\pi\theta_M\theta_m}{8ln2}} \end{equation}
   
   where :math:`h` is the pixel width of the direction coordinate and
   :math:`\mu` is the rms noise (see the discussion above for the
   rules governing how the value of :math:`\mu` is determined).
   
   For the correlated noise case, the same equations are used to
   determine the uncertainties as in the uncorrelated noise case,
   except for the uncertainty in :math:`I` (see below). However,
   :math:`\rho` is given by
   
   .. math:: \begin{equation} \rho = \frac{A}{\mu}\frac{\sqrt{\theta_M\theta_m}}{2\theta_N}\left(1 + \left(\frac{\theta_N}{\theta_M}\right)^2\right)^{\alpha_M/2}\left(1 + \left(\frac{\theta_N}{\theta_m}\right)^2\right)^{\alpha_m/2} \end{equation}
   
   where :math:`\theta_N` is the noise-correlation beam FWHM (see
   discussion of the *noisefwhm* parameter for rules governing how
   this value is determined). Variables :math:`\alpha_M` and
   :math:`\alpha_m` depend on which uncertainty is being calculated.
   For :math:`\sigma(A)`, :math:`\alpha_M` = :math:`\alpha_m` = 3/2.
   For :math:`\sigma_M` and :math:`x_0`, :math:`\alpha_M` = 5/2 and
   :math:`\alpha_m` = 1/2. For :math:`\theta_m`, :math:`y_0`, and
   :math:`\phi`, :math:`\alpha_M` = 1/2 and :math:`\alpha_m` = 5/2.
   :math:`\sigma(I)` is calculated in the correlated noise case
   according to
   
   .. math:: \begin{equation} \frac{\sigma(I)}{I} = \sqrt{ \left(\frac{\sigma(A)}{A}\right)^2 + \left(\frac{\theta_N^2}{\theta_M\theta_m}\right)\left[\left(\frac{\sigma(\theta_M)}{\theta_M}\right)^2 + \left(\frac{\sigma(\theta_m)}{\theta_m}\right)^2 \right] } \end{equation}
   
   Note well the following caveats:
   
   -  Fixing Gaussian component parameters will tend to cause the
      parameter uncertainties reported for free parameters to be
      overestimated.
   -  Fitting a zero level offset that is not fixed will tend to
      cause the reported parameter uncertainties to be slightly
      underestimated.
   -  The parameter uncertainties will be inaccurate at low SNR (a
      ~10% for SNR = 3).
   -  If the fitted region is not considerably larger than the
      largest component that is fit, parameter uncertainties may be
      mis-estimated.
   -  An accurate rms noise measurement, :math:`\mu`, for the region
      in question must be supplied. Alternatively, a sufficiently
      large signal-free region must be present in the selected region
      (at least about 25 noise beams in area) to auto-derive such an
      estimate.
   -  If the image noise is not statistically independent from pixel
      to pixel, a reasonably accurate noise correlation scale,
      :math:`\theta` :math:`_N`, must be provided. If the noise
      correlation function is not approximately Gaussian, the
      correlation length can be estimated using
   
   .. math:: \begin{equation} \theta_N = \sqrt{ \frac{2 \ln (2)}{\pi} } \, \frac{  \iint C(x,y) \mathrm{d}x \mathrm{d}y} { \sqrt{ \iint C(x,y)^2 \mathrm{d}x \mathrm{d}y}   } \end{equation}
   
   where C(x,y) is the associated noise-smoothing function.
   
   -  If fitted model components have significant spatial overlap,
      the parameter uncertainties are likely to be mis-estimated
      (i.e., correlations between the parameters of separate
      components are not accounted for).
   -  If the image being analyzed is an interferometric image with
      poor uv sampling, the parameter uncertainties may be
      significantly underestimated.
   
   The deconvolved size and position angle errors are computed by
   taking the maximum of the absolute values of the differences of
   the best fit deconvolved value of the given parameter and the
   deconvolved size of the eight possible combinations of (FWHM major
   axis +/- major axis error), (FWHM minor axis +/- minor axis
   error), and (position angle +/- position angle error). If the
   source cannot be deconvolved from the beam (if the best fit
   convolved source size cannot be deconvolved from the beam), upper
   limits on the deconvolved source size are reported, if possible.
   These limits simply come from the maximum major and minor axes of
   the deconvolved Gaussians taken from trying all eight of the
   aforementioned combinations. In the case none of these
   combinations produces a deconvolved size, no upper limit is
   reported.
