
   
   .. rubric:: Output Images
   
   Depending on the operation being run, a subset of the following
   output images will be written to disk.
   
   imagename = 'try'
   
   +-----------------------------------+-----------------------------------+
   | try.psf                           | Point Spread Function (PSF)       |
   +-----------------------------------+-----------------------------------+
   | try.pb                            | Primary Beam (PB)                 |
   +-----------------------------------+-----------------------------------+
   | try.residual                      | Residual Image (or initial Dirty  |
   |                                   | Image if niter=0)                 |
   +-----------------------------------+-----------------------------------+
   | try.model                         | Model Image after deconvolution   |
   +-----------------------------------+-----------------------------------+
   | try.image                         | Restored output image             |
   +-----------------------------------+-----------------------------------+
   | try.image.pbcor                   | Primary Beam corrected image      |
   |                                   | (non wide-band)                   |
   +-----------------------------------+-----------------------------------+
   | try.mask                          | Deconvolution mask                |
   +-----------------------------------+-----------------------------------+
   | try.sumwt                         | A single pixel image containing   |
   |                                   | sum of weights per plane          |
   +-----------------------------------+-----------------------------------+
   | try.weight                        | Image of un-normalized sum of     |
   |                                   | PB-square (for mosaics and        |
   |                                   | A-Projection)                     |
   +-----------------------------------+-----------------------------------+
   | try.psf.tt0, try.psf.tt1,         | Multi-term images representing    |
   | try.psf.tt2, try.model.tt0,       | Taylor coefficients (of           |
   | try.model.tt1, try.residual.tt0,  | polynomials that model the sky    |
   | try.residual.tt1, try.image.tt0,  | spectrum)                         |
   | try.image.tt1, etc...             |                                   |
   +-----------------------------------+-----------------------------------+
   | try.alpha                         | Spectral index, for multi-term    |
   |                                   | wideband imagging                 |
   +-----------------------------------+-----------------------------------+
   | try.alpha.error                   | Estimate of error on spectral     |
   |                                   | index                             |
   +-----------------------------------+-----------------------------------+
   | try.beta                          | Spectral curvature for multi-term |
   |                                   | wideband images (if nterms > 2)   |
   +-----------------------------------+-----------------------------------+
   | try_1.\*, try_2.\*, try_3\.*,     | Auto-incremented image names when |
   | etc.                              | restart=False                     |
   +-----------------------------------+-----------------------------------+
   | try1_1.\*, try1_2.\*,             | Auto-incremented image names with |
   | try1_3.\*, etc.                   | multiple fields when              |
   |                                   | restart=False                     |
   +-----------------------------------+-----------------------------------+
   | try.workdirectory                 | Scratch images written within a   |
   |                                   | 'work directory' for parallel     |
   | ( try.n1.psf, try.n2.psf,         | imaging runs for cube imaging.    |
   | try.n3.psf, try.n1.residual,      | The reference images are          |
   | try.n2.residual, try.n3.residual, | reference-concatenated at the end |
   | try.n1.weight, try.n2.weight,     | to produce single output cubes.   |
   | try.n3.weight, try.n1.gridwt,     | As of CASA 5.7, continuum imaging |
   | try.n2.gridwt, etc... )           | no longer produces a              |
   |                                   | try.workdirectory.                |
   |                                   |                                   |
   |                                   |                                   |
   +-----------------------------------+-----------------------------------+

   
   .. warning:: If an image with that name already exists, it will in
      general be overwritten. Beware using names of existing images
      however. If the tclean is run using an imagename where
      <imagename>.residual and <imagename>.model already exist, then
      tclean will continue starting from these (effectively
      restarting from the end of the previous tclean). Thus, if
      multiple runs of tclean are run consecutively with the same
      imagename, then the cleaning is incremental.

   .. tip:: To organize the output images produced by one or multiple
             runs of tclean and/or other imaging tasks, a subdirectory
             can be added to 'imagename'.  All output images will be
             sent to that directory instead of the current working
             directory. Example: imagename=’mydir/try’. This is a
             simple way to group together a set of images (different
             extensions) corresponding to a same sequence of tclean
             runs, preventing confusion and conflicts with the
             potentially long list of other images from related or
             unrelated tclean runs that used similar 'imagename'.

   .. rubric:: Stokes polarization products

   It is possible to make polarization images of various Stokes
   parameters, based on the R/L circular (e.g., VLA) or the X/Y
   linear (e.g., ALMA) polarization products. When specifying
   multiple values in the 'stokes' parameter, the output image will
   have planes (along the "polarization" axis) corresponding to the
   chosen Stokes parameters.
   
   The Stokes parameter is specified as a string of up to four
   letters, and can indicate stokes parameters themselves, Right/Left
   hand polarization products, or linear polarization products (X/Y).
   Examples include:
   
   ::
   
      stokes = 'I' # Intensity only (default)
      stokes = 'IQU' # Intensity and linear polarization
      stokes = 'IV' # Intensity and circular polarization
      stokes = 'IQUV' # All Stokes imaging
      stokes = 'RR' # Right hand polarization only
      stokes = 'XXYY' # Both linear polarizations
      stokes = 'pseudoI' # Intensity only, but including data with one of the parallel polarizations flagged
   
   For imaging the total intensity, the stokes='I' option is stricter
   than the stokes='pseudoI' option in the sense that it excludes all
   correlations for which any correlation is flagged, even though the
   remaining correlations are valid. On the other hand,
   the'pseudoI'option allows Stokes I images to include data for
   which either of the parallel hand data are unflagged. For example,
   if you have RR and LL dual polarization data and you flagged parts
   of RR but not LL, stokes='I' will ignore both polarizations in the
   time-stamps where RR are flagged, while stokes='pseudoI' will
   include all unflagged data in the total intensity image. See the
   CASA Docs pages on Types of
   Images and Single
   Dish Imaging
   (tsdimaging) for
   more information. It is also possible to split out a polarization
   product with split and image separately, but you will not be able
   to combine these part-flagged data in the uv-domain. 
