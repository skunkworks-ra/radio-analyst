


.. _Examples:

Examples
   .. _Basic_Usage:
   .. rubric:: Basic Usage

   Build the '.image' image from the '.residual' and '.psf' images, as given by tclean or some other task.

   .. code-block:: python

      from casatools import ctsys
      refim_path = ctsys.resolve('unittest/deconvolve/')

      # remove the old run, as necessary
      os.system("rm -rf try.*")

      # create the .residual and .psf images
      tclean(vis=refim_path+'refim_point.ms', imagename='try', imsize=100, cell='8.0arcsec', niter=0)

      # run deconvolve to generate the .image image
      ret=deconvolve(imagename='try', deconvolver='clark', niter=20) # “restoration” defaults to True

   This works for all of the common cases, including:

   .. TODO add mtmfs and asp
   .. TODO "2D, 3D, and 4D images/cubes" => "2D, 3D, and 4D images/cubes and multi-term (for mtmfs)"

   - All the deconvolvers (hogbom, clark, clarkstokes, multiscale)
   - 2D, 3D, and 4D images/cubes, regridded as appropriate to have axes [ra,dec,pol,chan]
   - Restoration with a common beam or restoringbeam
   - Masking (user, pbmask, automask)
   - With a different start model
   
   .. TODO uncomment in CAS-13570 once test_multirun_mtmfs3x passes
   ..   .. _Basic_Usage_with_MTMFS_Deconvolver:
   ..   .. rubric:: Basic Usage with MTMFS Deconvolver
   ..
   ..   Build the '.image.tt\*' images from the '.residual.tt\*' and '.psf.tt\*' images, as given by tclean or some other task. This
   ..   is an expansion on the Basic Usage example, showing how the 'nterms' parameter affects the taylor terms
   ..   image generation.
   ..
   ..   .. code-block:: python
   ..
   ..      from casatools import ctsys
   ..      refim_path = ctsys.resolve('unittest/deconvolve/')
   ..
   ..      # remove the old run, as necessary
   ..      os.system("rm -rf try.*")
   ..
   ..      # Use tclean to generate our taylor term images. This should produce the images:
   ..      # try.psf.tt0...try.psf.tt4, try.residual.tt0...try.residual.tt2, try.pb.tt0
   ..      tclean(vis=refim_path + 'refim_point.ms', imagename='try', imsize=10, cell='8.0arcsec',
   ..             deconvolver='mtmfs', niter=0, restoration=False, calcres=True, nterms=3)
   ..
   ..      # Deconvolve with the same deconvolver and nterms. This should produce the images:
   ..      # try.model.tt0...try.model.tt2, try.image.tt0...try.image.tt2, try.residual.tt0...try.residual.tt2
   ..      ret=deconvolve(imagename='try', niter=10, deconvolver='mtmfs', nterms=3)

   .. _Multiple_Runs:
   .. rubric:: Multiple Runs

   Run deconvolve multiple times. This can be done with all of the same parameters and the same deconvolver algorithm. This should
   give the same results as running deconvolve once with the same total number of iterations. With the code below, we should get
   the same result as when running the Basic Usage example.

   .. code-block:: python

      from casatools import ctsys
      refim_path = ctsys.resolve('unittest/deconvolve/')

      # remove the old run, as necessary
      os.system("rm -rf try.*")

      # create the .residual and .psf images
      tclean(vis=refim_path+'refim_point.ms', imagename='try', imsize=100, cell='8.0arcsec', niter=0)

      # run deconvolve for 20 total iterations (10x2)
      ret1=deconvolve(imagename='try', deconvolver='clark', niter=10, interactive=0)
      ret2=deconvolve(imagename='try', deconvolver='clark', niter=10, interactive=0)

   .. _Automasking_Experimentation:
   .. rubric:: Automasking Experimentation

   Task deconvolve can be used in conjunction with task tclean to quickly home in on the correct automasking parameters. Running the
   task many times in a row to watch how the mask evolves is much faster with deconvolve because the slow major cycle of tclean is avoided.

   .. code-block:: python

      ###############################################################################
      # autotest_script.py
      ###############################################################################

      import shutil

      def setup():
          '''Get the ms and evaluate tclean'''
          os.system('rm -rf try.* *.ms bak')
          os.system('mkdir bak')
          refdatapath = ctsys.resolve('unittest/deconvolve/')
          shutil.copytree(refdatapath+'refim_twochan.ms', 'refim_twochan.ms')

          tclean(vis='refim_twochan.ms', imagename='try', niter=0, imsize=100, cell='8.0arcsec', \
                 deconvolver='hogbom', usemask='auto-multithresh', restoration=False, calcres=True)
          os.system("cp -rp try.* bak/")

      def restore_files(restore=False):
          '''Get the image files for a clean deconvolution test'''
          os.system('rm -rf try.*')
          os.system('cp -rp bak/* ./')

      ### Try out different automasking parameters with deconvolve.
      ### Parameters to play with: sidelobethreshold, noisethreshold, lownoisethreshold, negativethreshold, smoothfactor, minbeamfrac, cutthreshold, growiterations, dogrowprune, fastnoise
      ### To be run with "casa -c autotest_script.py":
      setup() # only need to do this the first time running the script
      restore_files()
      # Evaluate some number of times with a for loop to watch how the automask evolves.
      for n in range(10):
          ret=deconvolve(imagename='try', niter=10, deconvolver='hogbom', interactive=True, usemask='auto-multithresh', verbose=True)

   .. _Multiple_Clean_Methods:
   .. rubric:: Multiple Clean Methods

   Start with one deconvolve method, then switch to a different deconvolve method. For example, the multiscale clean method is slow
   but makes quick progress in the beginning, so start with multiscale clean and then switch to the much faster hogbom clean.

   .. code-block:: python

      from casatools import ctsys
      g55path = ctsys.resolve('RSRO/SNR/LBand_G55.7+3.4')

      def run_G55(cycle, init=False, deconvolver='hogbom', niter=200):
          '''
          Run tclean's major cycle to get multiscale RHS images.
          Run deconvolve separately on this.
          '''
          if (init):
              print("Initializing!!!")

          if cycle=='major':
              if init==True:
                  os.system('rm -rf tdec_G55*')
              print("Running a major cycle with tclean")
              vis = g55path+'/G55.7+3.4_cal.ms'
              tclean(vis=vis, imagename='tdec_G55', deconvolver=deconvolver, gridder='wproject', \
                     wprojplanes=24, cell='8.0arcsec', imsize=1024, weighting='briggs', niter=0)

          elif cycle=='minor':
              print("Running a minor cycle")
              if deconvolver == 'hogbom':
                  ret=deconvolve(imagename='tdec_G55', deconvolver=deconvolver, niter=niter, \
                                 interactive=0)
              elif deconvolver == 'multiscale':
                  ret=deconvolve(imagename='tdec_G55', deconvolver=deconvolver, niter=niter, \
                                 interactive=0, scales=[0,6,10,20,30], smallscalebias=-0.6)
              else:
                  print("unrecognized deconvolver \""+deconvolver+"\"")
                  return

          else:
              print("Unrecognized cycle argument value \""+cycle+"\"")

      for i in range(5):
          run_G55(cycle='major', init=(i==0))
          run_G55(cycle='minor', deconvolver='multiscale', niter=5)
          run_G55(cycle='minor', deconvolver='hogbom', niter=195)

   .. _Correcting_Axes:
