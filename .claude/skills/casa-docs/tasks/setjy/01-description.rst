

.. _Returns:

Returns
   fluxd (dict) - flux densities indexed by field and SPW


.. _Description:

Description
   .. warning:: There are Known Issues for setjy.

   The **setjy** task sets the model visibility amplitude and phase
   associated with a flux density scale and a specified clean
   components image into the model column of the MS data set. The
   flux density (I,Q,U,V) for a point source calibrator can be
   entered explicitly.  If no model is specified, then a point source
   at the phase center is assumed.  For sources that are recognized
   flux calibrators (listed in Flux Calibrator
   Models ),
   setjy can calculate the flux densities as a function of frequency
   (and time, for some extragalactic sources classified as the
   variable sources and Solar System objects). Otherwise, the flux
   densities should be manually specified ( standard=’manual’).

   .. rubric:: Overview

   The basic modes of operations are specified by the parameter,
   *standard*. As the name indicates, the bulk of its options are
   different flux density standards available in CASA as listed in
   Flux Calibrator
   Models.
   In addition, *standard=’manual’* allows flux density scaling to be
   specified directly instead of using one for the flux density
   standards. And finally, *standard=‘fluxscale’* allows the user to
   insert a flux density based on the python dictionary result from
   the fluxscale task, after the initial **setjy** on the primary
   flux calibrator, to insert proper flux density models for
   secondary calibrators in the MS.

   By default the **setjy** task will cycle through all selected
   fields, spectral windows and channels, (one solution per spw with
   *scalebychan = False*) , setting the flux density either to 1 Jy
   (unpolarized), or if the source is recognized as one of the
   calibrators, to the flux density (assumed unpolarized) appropriate
   to the observing frequency.

   Optionally, the MODEL_DATA column can be filled with the Fourier
   transform of the model image. But for any given MeasurementSet,
   the performance and data storage requirements are less demanding
   without the MODEL_DATA column. If *usescratch=False*, the model
   is stored as a 'virtual' model. The model parameters are saved
   either in the SOURCE_MODEL column in the SOURCE table (if one
   exists) or in the keyword
   of the main table in the MS and model visibilities are evaluated
   on the fly when processing calibration or plotting in plotms.
   The result containing flux densities for each spw is returned as
   a Python dictionary when it is executed as the function with
   arguments,

   ::

      # For Example

      setjy(vis=‘my.ms’…)


   .. rubric:: Manually setting Flux Densities: standard=‘manual’

   With this mode, the flux densities and other relevant parameters
   necessary to describe the model can be entered manually. The
   following are the subparameters.

   ::

      standard       =   'manual'        #  Flux density standard
      fluxdensity    = [1, 0, 0, 0]      #  Specified flux density in Jy [I,Q,U,V]; (-1 will lookup values)
      spix           =         []        #  Spectral index (including higher terms) of I fluxdensity
      reffreq        =         ''        #  Reference frequency for spix
      polindex       =         []        #  Coefficients of an expansion of frequency-dependent linear
                                         #  polarization fraction expression
      polangle       =         []        #  Coefficients of an expansion of frequency-dependent polarization
                                         #  angle expression (in radians)
      rotmeas        =        0.0        #  Rotation measure (in rad/m^2)



   In the simplest version, the flux for Stokes I can be set via the
   *fluxdensity* subparameter as the first entry in a list. In the
   above example [1,0,0,0] **setjy** sets the flux to 1 Jy.
   Additional Stokes specifications can be set in remaining list
   members.  All *fluxdensity* vales **must** be given in units of
   Jy. A spectral index can be provided via the *spix* and *reffreq*
   subparameters. Finally it is also possible to provide coefficients
   for the polarization fraction and angle as well as a rotation
   measure to define the model (*polindex*, *polangle*, *rotmeas*
   subparameters).

   The *spix* subparamter can accept a list of values to include the
   spectral index of Stokes I in higher order terms, using the
   definition of the flux density at a frequency, :math:`\nu`,
   :math:`S(\nu)=fluxdensity[0]*\frac{\nu}{reffreq}^{spix[0]+spix[1]*log(\nu/reffreq)+..}`
   . The *reffreq* is given by a string including the unit (e.g.
   '10GHz', note that there is no space between the value and the
   unit). The *polindex* takes a list of coefficents ([p0, p1,
   p2...]) using the definition of frequency-dependent polarization
   index (PI) , where

   :math:`PI = \frac{\sqrt{Q^2+U^2}}{I} = p0 + p1*\frac{\nu-reffreq}{reffreq} + p2*(\frac{\nu-reffreq}{reffreq})^2 + ...`.

   Similarly, the *polangle* subparameter takes a list of
   coefficients ([a0,a1,a2, ..]) using the definition of polarization
   angle (:math:`\chi`), where

   :math:`\chi = 0.5arctan\frac{U}{Q} = a0 + a1*\frac{\nu-reffreq}{reffreq} + a2*(\frac{freq-reffreq}{reffreq})^2 + ..`.

   .. note:: Some logics how these subparameters are used to
      determine flux densities:

      -  When Stokes Q and U flux densities are given in
         *fluxdensity*, the coefficient, p0 is determined from these
         flux densities and the entry for p0 in *polindex* is
         ignored. Also, a0 is determined from these flux density
         values and the entry for a0 in *polangle* is ignored.
      -  If Q and U flux densities in fluxdensity are set to 0.0,
         then *polindex* [0] and *polangle* [0] are used to
         determine Q and U at *reffreq*.
      -  When the frequency-dependent polindex and polangle are used,
         be sure to include all the coefficients for **both**
         *polindex* and *polangle.* Otherwise Q and U flux densities
         are not calculated correctly.
      -  If *rotmeas* is given, the Q and U that are determined from
         above parameters are further corrected for the Faraday
         rotation.
