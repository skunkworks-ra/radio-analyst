
.. _Examples:

Examples
   The following examples, to be expanded, highlight modes and
   options that the tclean task supports.
   The examples below are written as scripts that may be copied
   and pasted to get started with the basic parameters needed for
   a particular operation. When writing scripts, it is advised
   that the interactive task interface be used to view lists of
   sub-parameters that are relevant only to the operations being
   performed. For example, setting specmode='cube' and running
   inp() will list parameters that are relevant to spectral
   coordinate definition, or setting niter to a number greater
   than zero (niter=100) followed by inp() will list iteration
   control parameters.
   Note that all runs of tclean need the following parameters:
   vis, imagename, imsize, and cell.
   By default, tclean will run with niter=0, making the PSF, a
   primary beam, the initial dirty (or residual) image and a
   restored version of the image.

   
   For examples running tclean on ALMA data, see also the ALMA `CASA Guide <https://casaguides.nrao.edu>`__ 'Tclean and
   ALMA', which can be found under the General Imaging Tutorial 'Examples for using the tclean CASA task for ALMA Imaging'.
   
   .. rubric:: Imaging and Deconvolution Iterations
   
   .. rubric:: Using Hogbom CLEAN on a single MFS image
   
   ::
   
      tclean(vis='test.ms', imagename='try1', imsize=100, cell='10.0arcsec', specmode='mfs',
             deconvolver='hogbom', gridder='standard', weighting='natural', niter=100 )
   
   .. rubric:: Using Multi-scale CLEAN on a Cube Mosaic image
   
   ::

      tclean(vis='test.ms', imagename='try1', imsize=100, cell='10.0arcsec',specmode='cube', nchan=10,
             start='1.0GHz', width='10MHz', deconvolver='multiscale', scales=[0,3,10,30], gridder='mosaic', pblimit=0.1,
             weighting='natural', niter=100 )
   
   .. rubric:: Using W-Projection with Multi-Term MFS wideband imaging

   ::
   
      tclean(vis='test.ms', imagename='try1', imsize=100, cell='10.0arcsec', deconvolver='mtmfs', reffreq='1.5GHz',
             nterms=2, gridder='wproject', wprojplanes=64, weighting='natural', niter=100 )
   
   .. rubric:: Using automasking with any type of image

   ::
   
      tclean(vis='test.ms', imagename='try1', niter=100, ...., usemask='auto-multithresh')
    
   
   .. rubric:: Scripting using PySynthesisImager

   PySynthesisImager is a python application built on top
   of the synthesis tools. The operations of the tclean
   task can be replicated using the following python script.
   Subsets of the script can thus be chosen, and extra external
   methods can be inserted in between as desired.  After each
   stage, images are saved on disk. Therefore, any modifications
   done to the images in between steps will be honored.

   ::
   
      ## (1) Import the python application layer
      from imagerhelpers.imager_base import PySynthesisImager
      from imagerhelpers.input_parameters import ImagerParameters

      ## (2) Set up Input Parameters
      ## - List all parameters that you need here
      ## - Defaults will be assumed for unspecified parameters
      ## - Nearly all parameters are identical to that in the task.
      ## Please look at the list of parameters under __init__
      ## using "help ImagerParameters"
      paramList = ImagerParameters(msname ='DataTest/point.ms',
                                   field='',
                                   spw='',
                                   imagename='try2',
                                   imsize=100,
                                   cell='10.0arcsec',
                                   specmode='mfs',
                                   gridder='standard',
                                   weighting='briggs',
                                   niter=100,
                                   deconvolver='hogbom')

      ## (3) Construct the PySynthesisImager object, with all input parameters
      imager = PySynthesisImager(params=paramList)

      ## (4) Initialize various modules.
      ## - Pick only the modules you will need later on. For
      example, to only make
      ## the PSF, there is no need for the deconvolver or iteration control modules.
      ## Initialize modules major cycle modules
      imager.initializeImagers()
      imager.initializeNormalizers()
      imager.setWeighting()
      ## Init minor cycle modules
      imager.initializeDeconvolvers()
      imager.initializeIterationControl()

      ## (5) Make the initial images
      imager.makePSF()
      imager.makePB()
      imager.runMajorCycle() # Make initial dirty / residual image

      ## (6) Make the initial clean mask
      imager.hasConverged()
      imager.updateMask()

      ## (7) Run the iteration loops
      while ( not imager.hasConverged() ):
          imager.runMinorCycle()
          imager.runMajorCycle()
          imager.updateMask()

      ## (8) Finish up
      retrec=imager.getSummary();
      imager.restoreImages()
      imager.pbcorImages()

      ## (9) Close tools.
      imager.deleteTools()
   
    
   For model prediction (i.e. to only save an input model in
   preparation for self-calibration, for example), use the
   following in step (5). The name of the input model is either
   assumed to be <imagename>.model (or its multi-term equivalent)
   or should be specified via the startmodel parameter in step
   (2).
    
   
   ::
   
      imager.predictModel()      # Step (5)
   
   For major cycle parallelization for continuum imaging
   (specmode='mfs'), replace steps (1) and (3) with the following

   
   ::
   
      # Step (1)
      from imagerhelpers.imager_parallel_continuum import PyParallelContSynthesisImager

      # Step (3)
      imager = PyParallelContSynthesisImager(params=paramList)

   
   For parallelization of both the major and minor cycles for Cube
   imaging, replace steps (1) and (3) with the following, and
   include a virtual concanenation call at the end. (However, note
   that for parallel Cube imaging, if you would like to replace
   the minor cycle with your own code (for example), you would
   have to go one layer deeper. For this, please contact our team
   for assistance.)
   
   ::
   
      from imagerhelpers.imager_parallel_cube import PyParallelCubeSynthesisImager   # Step (1)
      imager = PyParallelCubeSynthesisImager(params=paramList) # Step (3)
      imager.concatImages(type='virtualcopy') # Step (8)
