
   .. rubric:: Imaging and Deconvolution Options

   Parameters that control interferometer-gridding/imaging and
   deconvolution options are *specmode, gridder, deconvolver* (and
   associated sub-parameters similar to **tclean**).

   -  **Specmode** : Supported modes include  *specmode='cube'* with
      any single-term deconvolver, and  *specmode='mfs'* with any
      deconvolver (including multi-term). These options represent
      different conversion routines between the feathered cubes and
      the inputs/outputs for deconvolution.

      -  *‘cube’*: the cubes are sent as is to the deconvolver and
         the output model cube is directly passed to the major cycle.
      -  *‘mfs’*: the cubes are averaged to form a continuum image
         and continuum PSF prior to deconvolution and the model image
         is expanded out to an image model cube prior to the next
         major cycle.
      -  *‘mtmfs’*: the cubes are converted to Taylor-weighted
         averages in accordance with the MTMFS algorithm and the
         model Taylor coefficient image output from the deconvolver
         are evaluated back onto a model image cube prior to the
         major cycle. This image reshaping follows the diagram at the
         top of this page.

   All frequency averages in the Cube to Taylor conversions and in
   the calculation of a common Primary Beam use the interferometer
   sum-or-weight spectrum as frequency-dependent weights, multiplied
   by a 1-0 flag to identify channels with valid images in both the
   SD and INT cubes

   -  **Deconvolvers** : Algorithms supported are *‘multiscale',
      'hogbom’* and *'clark'* for *cube* and *mfs(nterms=1)* imaging
      and *‘mtmfs’* for multi-term mfs imaging. However, for use
      cases where single dish data are required along with
      interferometer data, multiscale deconvolution is most
      appropriate to get accurate reconstructions at multiple spatial
      scales. The *‘multiscale’* deconvolver applies to
      *specmode=’cube’* and *'mfs(nterms=1)’* and the *‘mtmfs’*
      deconvolver applies to the *specmode=’mfs(nterms>1)’*. In all
      cases, the *‘scales’* parameter is also relevant as it sets the
      list of scale sizes to use during deconvolution. Beware of choosing
      a too large maximum scale size! This may lead to random flux offsets
      between different channels of the combined cube! Choose the maximum
      scale size smaller than the typical entend of the emission in the image.
      The *‘hogbom’* deconvolver is relevant only when used with *usedata=’sdonly’*
      to deconvolve unresolved sources.

   -  **Gridders** :  All gridders supported by task tclean may be
      used with **sdintimaging**. Two options that represent
      different normalization schemes are *'standard'* and *'mosaic'*
      (or *'awproject'*). Similar to tclean, the  *‘standard’*
      gridder does not consider primary beams and represents one mode
      of operation that is valid only in the central region of the
      interferometer primary beam. The *‘mosaic’* and *'awproject'*
      gridders account for primary beams and are appropriate for
      full-beam or joint mosaic images.  For these two A-Projection
      gridders, the normtype is always *'flatnoise'* and conjbeams is
      implemented via an image-domain scheme not offered by task
      tclean.  **Note** also that the *‘awproject’* gridder is currently
      unavailable with the sdintimaging task. This usage mode will be
      commissioned in a future release when it is enabled for cube
      imaging in tclean as well.


   .. rubric:: Iteration Control and Automasking

   Iteration contol and automasking parameters are identical to those
   used in task tclean, with the same rules and conventions applied
   to stopping criteria.


   .. rubric:: Output Images

   The sdintimaging task presently produces many
   intermediate images which persist after the end of the task.  The
   naming convention of the images is more complex than the tclean
   task.

   +-----------------------------------+-----------------------------------+
   | <imagename>.sd.cube.{image,psf}   | Image cubes onto which the input  |
   |                                   | Single Dish image and psf cubes   |
   | <im                               | are regridded.                    |
   | agename>.sd.cube.{model,residual} |                                   |
   |                                   | Intermediate products containing  |
   |                                   | the model image cube that is      |
   |                                   | subtracted from the SD image to   |
   |                                   | make the SD residual              |
   +-----------------------------------+-----------------------------------+
   | <imagename>.int.cube.{residual,   | Image cubes made from only the    |
   | psf, sumwt,weight,pb)             | interferometer data               |
   |                                   |                                   |
   | <imagename>.int.cube.{model}      | Intermediate product. Cube model  |
   |                                   | image used for model prediction   |
   |                                   | and residual calculation.         |
   +-----------------------------------+-----------------------------------+
   | <imagename>.joint.cube.{residual, | Feathered cubes for the residual  |
   | psf}                              | and psf.   For cube minor cycles, |
   |                                   | these are also the inputs to the  |
   | <imagename>.joint.multite         | deconvolver.                      |
   | rm.{residual,psf}.{tt0,tt1[,tt2]} |                                   |
   |                                   | Multi-term residual images and    |
   |                                   | spectral PSFs constructed from    |
   |                                   | the above feathered cubes. These  |
   |                                   | are inputs to the minor cycle for |
   |                                   | multi-term deconvolution          |
   +-----------------------------------+-----------------------------------+
   | <imagename>.joint.cube.{image,    | For cube minor cycles, all        |
   | sumwt, weight, pb,model,          | standard data products            |
   | mask,pbcor}                       |                                   |
   +-----------------------------------+-----------------------------------+
   | <i                                | For multi-term minor cycles, all  |
   | magename>.joint.multiterm.{image, | standard data products            |
   | sumwt, weight, pb, model, mask,   |                                   |
   | alpha,pbcor}  with  {.tt0, .tt1,  |                                   |
   | .tt2 } extensions as appropriate. |                                   |
   +-----------------------------------+-----------------------------------+

   This long list of output and intermediate images is likely to be
   pruned in a future release.

   .. rubric:: Model Prediction

   For usedata=‘int’ , one may wish to save a sky model to the MeasurementSet for later use such as self-calibration.  The **tclean** task can be used
   in such instances after executing sdintimaging. The model prediction can be done by
   running tclean with niter=0 and
   specifying savemodel=‘modelcolumn’ or ’ virtual’. For example,

   ::

       sdintimaging(usedata=‘int’, vis=‘xxx.ms’, imagename=‘tst-intonly’, ... niter=1000, ...)
       tclean(vis=‘xxx.ms’, imagename=‘tst-intonly', ... niter=0, savemodel=‘modelcolumn’, calcpsf=False, calcres=False, restoration=False)


   For more information and examples on the functionality of the
   sdintimaging task, see the CASA Docs chapter page on Joint
   Single Dish and Interferometer Image
   Reconstruction

   .. |image1| image:: _apimedia/c914c39a74a69699c2ae1d84231e2133af6d7081.png
