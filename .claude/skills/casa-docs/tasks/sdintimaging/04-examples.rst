

.. _Examples:

Examples
   To run sdintimaging with automatic SD-PSF generation, n-sigma
   stopping thresholds, a pb-based mask at the 0.3 gain level, and no
   other deconvolution masks (interactive=False).  Use the helper
   function shown below to extract frequency information from the sd
   cube to supply as input to sdintimaging.  Note that the sdimage
   cube must contain per-plane restoring beams.

   ::

      from sdint_helper import \*
      sdintlib = SDINT_helper()
      sdintlib.setup_cube_params(sdcube='M100_TP')
         Output : Shape of SD cube : [90 90  1 70]
         Coordinate ordering : ['Direction', 'Direction', 'Stokes',
         'Spectral']
         nchan = 70
         start = 114732899312.0Hz
         width = -1922516.74324Hz
         Found 70 per-plane restoring beams#
         (For specmode='mfs' in sdintimaging, please remember to set
         'reffreq' to a value within the freq range of the cube)
         Returned Dict : {'nchan': 70, 'start': '114732899312.0Hz',
         'width': '-1922516.74324Hz'}

      sdintimaging(usedata="sdint", sdimage="../M100_TP",
                   sdpsf="",sdgain=3.0, dishdia=12.0, vis="../M100_12m_7m",
                   imagename="try_sdint_niter5k", imsize=1000, cell="0.5arcsec",
                   phasecenter="J2000 12h22m54.936s +15d48m51.848s", stokes="I",
                   specmode="cube", reffreq="", nchan=70,
                   start="114732899312.0Hz", width="-1922516.74324Hz",
                   outframe="LSRK", veltype="radio", restfreq="115.271201800GHz",
                   interpolation="linear", perchanweightdensity=True,
                   gridder="mosaic", mosweight=True,
                   pblimit=0.2, deconvolver="multiscale", scales=[0, 5, 10, 15, 20],
                   smallscalebias=0.0, pbcor=False, weighting="briggs",
                   robust=0.5, niter=5000, gain=0.1, threshold=0.0, nsigma=3.0,
                   interactive=False, usemask="user", mask="", pbmask=0.3)

   For test-results using these parameters, and for additional
   test-results, see the CASA Docs chapter page on Joint Single Dish
   and Interferometeric Image
   Reconstruction.


.. _Development:

Development
   This page gives an overview of the code design and future
   development work that needs to be done. Detailed information on
   the algorithm can be found on the chapter page on Joint Single
   Dish and Interferometer Image
   Reconstruction,
   while a description of the **sdintimaging** task and associated
   parameters can be found on the
   sdintimaging
   task pages.


   .. rubric:: Code Design

   The sdintimaging task is implemented using the PySynthesisImager
   module in CASA.

   **Core algorithm implementation**: sdint_imager.py and
   sdint_helper.py

   sdint_imager contains main setup fuctions using PySnthesisImager:
   setup_imager, setup_deconvolver, setup_sdimaging as well as main
   joint imaging alogrithm (do_reconstruct). The sdint_helper
   provides helper functions such as feathering of sd + int, single
   dish residual calculation, primary beam manipulation, checks for
   consistency between SD and INT cube coordinate systems, etc.

   As shown in the diagram at the top of this page, a feathering step
   is inserted in between major and minor cycles to combine SD
   residual and interferometer residual images as well as PSFs before
   deconvolution. Apart from this, standard major/minor cycle
   iterations are performed and most imaging modes of task tclean are
   preserved.  However, only the above documented subset of modes
   have been tested.


   .. rubric:: Future work

   The following is a list of features that are either not available
   yet or currently untested with the sdintimaging task (or known
   bugs):

   -  Use of task_deconvolve for sd only.

   -  Fully test and characterize ‘int-only’ as a wideband mosaic option

   -  Add the ability to specify only the SD image cube and have the interferometer cube coordinate system be generated to match it.

   -  Improve how task feather works on cubes with per-plane restoring beams

   -  Understand why the feather step results in NaNs if the pblimit is set to a negative value for joint mosaic imaging of the INT data.

   -  Stop the ‘imageregrid’ warnings for every single run, which are given even if the SD cell size and beam are compatible.

   -  Add tools to check the relative flux densities of single-dish and interferometer visibility data to verify the results of joint deconvolution and other combination techniques.

   -  Check if restoration can happen with niter=0.

   -  Use sdint_helper:: setup_cube_params() to autogenerate nchan/start/width and then remove some parameters from the sdintimaging task interface, and check for validity of the input Single Dish image and PSF cubes

   -  If it is not possible to run ‘imregrid’, provide guidance to users on what to do.

   -  Connect to tsdimaging internally for ALMA data.




