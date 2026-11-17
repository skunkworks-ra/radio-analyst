

.. _Returns:

Returns
   summary (dict) - convergence history of the run, when
   interactive=1/0 instead of True/False


.. _Description:

Description
   The sdintimaging task allows joint reconstruction of wideband single dish
   and interferometer data.

   .. warning::

      The experience with joint reconstruction of wideband single dish and interferometer data with sdintimaging in
      CASA is limited. Please pay close attention to the description of tested usage modes in the CASA Docs chapter page on  Joint Single Dish
      and Interferometer Image Reconstruction

      .. warning:: There is a Known Issues for sdintimaging: gridder=’awproject’ is not yet available. It will be enabled in a future release.

   Interferometer data are gridded into an image cube (and
   corresponding PSF). The single dish image and PSF cubes are
   combined with the interferometer cubes in a feathering step. The
   joint image and PSF cubes then form inputs to any deconvolution
   algorithm (in either cube or mfs/mtmfs modes). Model images from
   the deconvolution algorithm are translated back to model image
   cubes prior to subtraction from both the single dish image cube as
   well as the interferometer data to form a new pair of residual
   image cubes to be feathered in the next iteration. In the case of
   mosaic imaging, primary beam corrections are performed per channel
   of the image cube, followed by a multiplication by a common
   primary beam, prior to deconvolution. Therefore, for mosaic
   imaging, this task always implements conjbeams=True and
   normtype=’flatnoise’.

   |image1|

   A more detailed description of the underlying algorithm, as well
   as results from its testing, can be found on the CASA Docs chapter
   page on Joint Single Dish and Interferometer Image
   Reconstruction.
   Note that the above diagram shows only the 'mtmfs' variant. Cube
   deconvolution proceeds directly with the cubes in the green box
   above, without the extra conversion back and forth to the
   multi-term basis. Primary beam handling is also not shown in this
   diagram, but full details (via pseudocode) are available in
   the `reference
   publication. <https://iopscience.iop.org/article/10.3847/1538-3881/ab1aa7>`_


   .. rubric:: Task Specification : sdintimaging

   The sdintimaging task shares a significant number of parameters
   with the tclean task. In the description below, parameters that
   are specific to sdintimaging are listed with full details, but all
   others will reference the existing tclean parameter documentation.

   .. rubric:: Multiple MSes

   -  Multiple MSes given as a list in vis is supported as in **tclean**.
      The details on the conformance checks that are performed on the list of the MSes
      are summarized in the CASA Docs on Combining Datasets.


.. rubric:: Data Selection

   -  All data selection options allowed for interferometer data.
      This set of parameters is identical to those in task
      **tclean**.


   .. rubric:: Image Definition

   -  Spatial dimensions are defined via the parameters : *imsize,
      cell, phasecenter, projection*

   -  Spectral dimensions for the major cycle are defined for cubes
      : *nchan,start, width, outframe, veltype, restfreq, interpolation*

   -  Spectral dimensions for the minor cycle are chosen based on
      specmode.  For *specmode='cube'* the minor cycle follows the
      same channelization as the major cycle. For *specmode='mfs'*,
      the choice of deconvolver and the setting of *'reffreq'* will
      decide the spectral coordinate system of the wideband image
      that is created after collapsing the cube images from the major
      cycle. For *deconvolver='mtmfs'* the appropriate cube-to-taylor
      (and reverse) conversions are applied.

   .. rubric:: Specifying Both Cube and MFS settings (for *specmode='mfs'*) :

   In **sdintimaging**, with MFS deconvolution, one *needs to specify
   both cube and mfs settings for frequency coordinates because in
   this usage mode the major cycle is done with cubes and the minor
   cycle with mfs*. This detail is different from the tclean task.  A
   few general rules to follow for a MFS (or MTMFS) minor cycle are

   -  The reffreq must lie between the ends of the cube frequency
      range (default based on data selection, or explicitly specified
      using *start, width, nchan*).  If this is not the case, an
      error message will appear.  If left at its default value of
      *reffreq=''*, it will be automatically computed to be the mean
      of the first and last channel frequencies and a log message is
      printed with the new value.

   -  For a wideband imaging run with nterms, at least nterms
      channels must be present in the input cubes. Ideally, in order
      to fully capture spectral variations and also guard against
      missing data, it is recommended that the cube be defined with
      between 5 and 20 channels. More may of course be used,
      especially in order to avoid bandwidth smearing within
      channels, but a larger number of channels will cause the
      feathering step to take longer.  Warnings are printed if the
      nchan of the cube is small (less than 5) or too large (more
      than 50), and the task will exit with an error if nchan <
      nterms.

   -  The sdintimaging task will perform the above checks on the
      input parameters and report problems/warnings as appropriate.
      The internal automation of some of these settings is on our
      'Future Work' list.
