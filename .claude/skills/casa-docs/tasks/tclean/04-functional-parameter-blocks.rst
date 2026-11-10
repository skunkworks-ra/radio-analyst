
   
   .. rubric:: Functional Parameter Blocks
   
   The **tclean** parameters are arranged in the functional blocks
   described below. More details on the individual parameters and
   sub-parameters can be found under the Parameters tab at the top of
   this page.
   
   As a general rule, sub-parameters will appear (and be used) only
   when a parent parameter has a specific value. This means that for
   a given set of choices (e.g. deconvolution or gridding algorithm)
   only parameters that are relevant to that choice will be visible
   to the user when " inp() " is invoked. Care should be taken when
   constructing tclean scripts that call the task as a python call 
   " tclean(....) ", to make sure that parameters and sub-parameters  
   that are relevant to the run are included.

   
   .. rubric:: Data Selection (selectdata)
   
   Selection parameters allow the definition of a subset of the
   supplied MS (or list of MSs) on which the imaging is to operate.
   Details can be found on the CASA Docs pages of Visibility
   Selection.

   
   .. rubric:: Image Definition (specmode)
   
   The image coordinate system(s) and shape(s) can be set up to form
   single images (from a single field or from multiple fields forming
   a mosaic),or multiple fields. The different modes for imaging
   include:
   
   -  'mfs': multi-frequency synthesis, i.e., continuum imaging with
      only one output image channel.
   -  'cube': Spectral line imaging with one or more channels. The
      fixed spectral frame, LSRK, will be used for automatic internal
      software Doppler tracking so that a spectral line observed over
      an extended time range will line up appropriately.
   -  'cubedata': Spectral line imaging with one or more channels
      There is no internal software Doppler tracking so a spectral
      line observed over an extended time range may be smeared out in
      frequency.
   -  'cubesource': Spectral line imaging while tracking moving
      source (near field or solar system ephemeris
      objects ).
      The velocity of the source is accounted and the frequency
      reported is in the source frame.
   
   Combined use of the parameters 'specmode' and 'gridder' (see
   below) allows to specify smaller outlier fields, facetted images,
   single plane wideband images (with 1 or more Taylor terms to model
   spectra), 3D spectral cubes with multiple channels, 3D images with
   multiple Stokes planes, 4D images with frequency channels and
   Stokes planes. Various combinations of all these options are also
   supported.
   
   The  CASA Docs pages on Image
   Types  provide
   more details.

   
   .. rubric:: Gridding Options (gridder)
   
   Options for convolutional resampling include standard gridding
   using a prolate spheroidal function, the use of FTs of Fresnel
   kernels for W-Projection, the use of baseline aperture
   illumination functions for A-Projection and Mosaicing. These
   include:
   
   -  'standard': standard gridding using a prolate spheroidal
      function
   -  'wproject': use of FTs of Fresnel kernels to correct for the
      widefield non-coplanar baseline effect (Cornwell et.al 2008)
   -  'widefield': Facetted imaging with or without W-Projection per
      facet.
   -  'mosaic': A-Projection that uses baseline, frequency and time
      dependent primary beams, without sidelobes, beam rotation or
      squint correction.
   -  'awproject': A-Projection from aperture illumination models
      with azimuthally asymmetric beams, including beam rotation,
      squint correction, conjugate frequency beams and W-projection
      (Bhatnagar et.al, 2008). 
   -  'awp2': A-Projection from aperture illumination models with
      azimuthally asymmetric beams, including squint correction,
      beam rotation, and W-projection. 

   .. note:: The awp2 gridder will eventually replace the existing
             awproject gridder in a future CASA release. At the moment both
             gridders only support A-projection with the EVLA primary beam.
             While they both implement the same algorithm, there are a few key
             differences in the implementation details:

             - awp2 has several bugfixes and feature improvements, and improved
               runtime performance compared with the 'awproject' gridder
             - awp2 is the recommended gridder for widefield polarization mosaics (W-Term + polarization).
             - awp2 does not write a persistent CFCache. The CFs are generated on the fly
               during the gridding process.
             - awp2 does **not** implement the "conjbeams" functionality, so in order to
               obtain the correct broadband spectral indices please use `specmode='mvc'`
               rather than `specmode='mfs'` with the `deconvolver=mtmfs`.

   .. warning:: The awp2 gridder has only been validated within the main lobe of the primary beam.
                Using a primary beam threshold that includes the sidelobes will yield incorrect results
                at this time. We expect this to be fixed in a future release.
   
   Combinations of these options are also available. For more information,
   see the parameter description below, or the CASA Docs pages on Widefield
   Imaging.
   
   For mosaicing and AW-projection, the frequency dependence of the
   primary beam within the data being imaged is included in the
   calculations and can optionally also be corrected for during
   gridding. See the CASA Docs page on Wideband
   Imaging for
   details.

   
   .. rubric:: Deconvolution Options (deconvolver)
   
   All the algorithms follow the Cotton-Schwab CLEAN style of major
   and minor cycles with the details of the deconvolution algorithm
   usually contained within the minor cycle and operating in the
   image domain. Options include:
   
   -  'hogbom': An adapted version of Hogbom Clean (Hogbom, 1974)
   -  'clark': An adapted version of Clark Clean (Clark, 1980)
   -  'clarkstokes': Clark Clean operating separately per Stokes
      plane
   -  'multiscale': MultiScale Clean (Cornwell, 2008).
      Scale-sensitive deconvolution algorithm designed for images
      with complicated spatial structure. It parameterizes the image
      into a collection of inverted tapered paraboloids.
   -  'mtmfs': Multi-term (Multi Scale) Multi-Frequency Synthesis
      (Rau and Cornwell, 2011). Models the wide-band sky brightness
      distribution through the use of multi-term Taylor polynomial
      and wideband primary beam corrections (to be used with
      nterms>1).
   -  'mem': Maximum Entropy Method (Cornwell and Evans, 1985). Note:
      This algorithm is **experimental** and not very robust, 
      improvements will be made in the future.
   -  'asp': Adaptive Scale Pixel Clean. The Adaptive Scale Pixel (ASP) 
      decomposition algorithm is designed to reconstruct the sky 
      brightness by adaptively determining the optimal scales. The 
      implementation of ASP algorithm is aimed to improve both image 
      resolution and computation efficiency. 
   
   If as input to tclean the stokes parameter includes polarization
   planes other than I, then choosing deconvolver='hogbom' or
   'clarkstokes' will clean (search for components) each plane
   sequentially, while deconvolver ='clark' will deconvolve jointly.
   
   For more details, see the CASA Docs pages on Deconvolution
   Algorithms.
   
   Several options for making masks, including
   automasking,
   are also provided.
