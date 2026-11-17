
   
   .. rubric:: Data Weighting (weighting)
   
   Data weighting during imaging allows for the improvement of the
   dynamic range and the ability to adjust the synthesized beam
   associated with the produced image. The weight given to each
   visibility sample can be adjusted to fit the desired output. There
   are several reasons to adjust the weighting, including improving
   sensitivity to extended sources or accounting for noise variation
   between samples. The user can adjust the weighting by changing the
   *weighting* parameter with seven options: 'natural', 'uniform',
   'briggs',  'superuniform', 'briggsabs', 'briggsbwtaper', and 'radial'. Optionally,
   a UV taper can be applied, and various parameters can be set to
   further adjust the weight calculations.
   
   The most used options for data weighting are 'natural', 'unform'
   and 'briggs'.
   
   -  'Natural' weighting gives equal weight to all samples,
      resulting in the lowest noise level and largest (poorest)
      resolution, with relatively high sidelobe levels.
   -  'Uniform' weighting gives a weight inversely proportional to
      the sampling density function, which minimizes sidelobe levels
      and provides higher resolution, but at the expense of higher
      noise levels.
   -  'Briggs' weighting provides a compromise between natural and
      uniform weighting, and often optimizes between angular
      resolution, noise, and sidelobe levels. The key parameter for
      briggs weighting is the robust sub-parameter, which takes
      value between -2.0 (close to uniform weighting) to 2.0 (close
      to natural). The scaling of R is such that robust=0 gives a good
      trade-off between resolution and sensitivity.
   
   In addition to the weighting scheme specified via the 'weighting'
   parameter, additional weights can be applied:
   
   -  The 'uvtaper' parameter applies a Gaussian taper on the weights
      of the UV data, in addition to the weighting scheme specified
      via the 'weighting' parameter. It is equivalent to smoothing
      the PSF obtained by other weighting schemes and can be
      specified either as a Gaussian in uv-space (eg. units of lambda
      or klambda) or as a Gaussian in the image domain (eg. angular
      units like arcsec). The effect of uvtaper this is that the
      clean beam becomes larger, and surface brightness sensitivity
      increases for extended emission.
   -  The 'perchanweightdensity' parameter (for briggs and uniform
      weighting of cubes) determines whether to calculate the
      weight density for each channel independently (True) or a
      common weight density for all of the selected data (False). In
      general, perchanweightdensity=True (default since CASA 5.5)
      provides more uniform sensitivity per channel for cubes, but
      with generally larger PSFs, while perchanweightdensity=False
      results in smaller psfs for the same robustness value, but the
      rms noise as a function of channel varies and increases toward
      the edge channels.
   -  The 'mosweight' sub-parameter of the mosaic gridder determines
      whether to weight each field in a mosaic independently
      (mosweight = True), or to calculate the weight density from the
      average uv distribution of all the fields combined (mosweight =
      False). For ALMA it has been shown that mosweight = True
      (default since CASA 5.4) may give better results in the
      presence of poor uv-coverage or non-uniform sensitivity across
      the mosaic, but the downside is that the major and minor axis
      of the synthesized beam may be ~10% larger than with
      mosweight=False, and it may potentially cause memory issues for
      large VLA mosaics.
   
   More details on data weighting can be found on the Image
   Algorithm pages
   of CASA Docs

   
   .. rubric:: Iteration Control (niter)
   
   Iterations are controlled by user parameters (gain, niter, etc..)
   as well as stopping criteria that decide when to exit minor cycle
   iterations and trigger the next major cycle, and also when to
   terminate the major-minor loop. These stopping criteria include
   reaching iteration limits, convergence thresholds, and signs of
   divergence with appropriate messages displayed in the log. For
   more details, see the CASA Docs pages on Iteration
   Control .


   .. rubric:: Other Options
   
   .. rubric:: Handling Large Data and Image Sizes
   
   Parallelization of the major cycle is available for continuum
   imaging and of both major and minor cycles for cube imaging. In
   order to run tclean in parallel mode it is necessary to launch
   CASA with mpicasa, and set the tclean parameter parallel=True. The
   parallelization of tclean works in the same way if the input is a
   normal MS or a Multi-MS (MMS), and thus differs from the parallel
   approach used by other tasks in that it does not require a
   partitioned MMS file. Details can be found in the CASA Docs
   chapter on Parallel
   Processing .
   
   For large image cubes, the gridders can run into memory limits as
   they loop over all available image planes for each row of data
   accessed. To prevent this problem, we can grid subsets of channels
   in sequence with the chanchunks parameter, so that at any given
   time only part of the image cube needs to be loaded into memory.
   The chanchunks parameter controls the number of chunks to split
   the cube into.
   
   .. rubric:: User Interaction

   .. warning:: Interactive use of tclean is based on the CASA Viewer, which is deprecated. 
   A stand-alone interactive tclean widget is currently under development. See this
   Viewer-end-of-Life page for details. 

   Options for user interaction include interactive
   masking
   and editing of iteration control parameters. The output log
   files can
   also be used to diagnose issues that may arise.
   
   Several convenience features are also available in the interactive mode, 
   such as operating
   on the MS in read-only mode (which does not require write
   permissions), the ability to restart and continue imaging runs
   without incuring the unnecessary cost of an initial major cycle or
   PSF construction and the optional return of a python dictionary
   that contains the convergence history of the run.
   
   .. rubric:: Scripting Controls
   
   Finer control can be achieved using the PySynthesisImager tools to
   run, e.g., only image domain deconvolution, to insert
   methods for automatic mask generation in between the
   existing major/minor cycle loops, or to connect external methods or
   algorithms for either the minor or major cycles.
