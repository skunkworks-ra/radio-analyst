

.. _Returns:

Returns
   summary (dict) - convergence history of the run, when
   interactive=1/0 instead of True/False

.. _Description:

Description
   The tclean task forms images from visibilities and reconstructs a sky model. 

   .. warning:: There are Known Issues for tclean 

   tclean handles continuum images and spectral line cubes, full
   Stokes polarization imaging, supports outlier fields, contains
   point-source CLEAN
   based algorithms as
   well as options for multi-scale and wideband image
   reconstruction ,
   widefield imaging correcting for the w-term, full primary-beam
   imaging and joint mosaic imaging (with heterogeneous array support
   for ALMA). Parallelization of the major cycle is also available.
   
   The tclean task as based on the `CLEAN
   algorithm <https://www.cv.nrao.edu/~abridle/deconvol/node7.html>`__ ,
   which is the most popular and widely-studied method for
   reconstructing a model image based on interferometer data. It
   iteratively removes at each step a fraction of the flux in the
   brightest pixel in a defined region of the current “dirty” image,
   and places this in the model image.
   
   Image reconstruction in CASA typically comprises an outer loop of
   *major cycles* and an inner loop of *minor cycles*. The major
   cycle implements transforms between the data and image domains and
   the minor cycle operates purely in the image domain. Together,
   they implement an iterative weighted :math:`\chi^2` minimization
   that solves the measurement
   equation.
   Minor cycle algorithms can have their own (different) optimization
   schemes, and the imaging framework and task interface allow for
   considerable freedom in choosing options separately for each step
   of the process.
   
   .. figure:: _apimedia/26ad14d4f63ff633dbd5d9e92d40a5059ab46a67.png

      Schematic overview of the iterative image reconstruction in the CASA task 
      tclean. The input 'DATA' are the calibrated visibilities. The left (red) and
      right (green) boxes show the major and minor cycle, respectively. 
      After gridding the visibilities and applying an inverse fast
      Fourier transform (iFFT), deconvolution on the (residual) image is done in the
      minor cycle. At the end of the minor cycle, the model image is translated back
      into the (u, v)-domain with a fast Fourier transform (FFT), where it is
      subtracted from the visibility data at the start of the next major cycle.

   .. rubric:: Operating Modes

   The tclean task can be configured to perform either full iterative
   image reconstructions
   (see synthesis-imaging )
   or to run each step separately. Parameters for data selection,
   image definition, gridding and deconvolution algorithms,
   restoration and primary beam setup are shared between all
   operational modes.
   
   The main usage modes of tclean are:
   
   -  .. rubric:: Imaging and Deconvolution Iterations:
   
   Construct the Point Spread Function (PSF) and Dirty image and apply a
   deconvolution algorithm to reconstruct a Sky model. A series of major 
   and minor cycle iterations are usually performed. The output sky model 
   is then restored and optionally corrected for the standard primary beam 
   response (optional wideband primary beam correction has to be applied 
   using the task widebandpbcor). The Sky model can optionally be saved 
   in the MS during the last major cycle.
   
   -  .. rubric:: Make PSF and PB:
   
   Make only the Point Spread Function and the Primary Beam, along
   with auxiliary weight images; a single pixel image containing
   sum-of-weight per plane, and (for mosaic and aprojection) a weight
   image containing the weighted sum of PB square.
   
   -  .. rubric:: Make a Residual/Dirty Image:
   
   Make a dirty image, or a new residual image using an existing or
   specified model image. This step requires the presence of the
   sum-of-weight and weight images (for normalization) constructed
   during the PSF and PB generation step.
   
   -  .. rubric:: Model Prediction:
   
   Save a sky model in the MeasurementSet for later use in
   calibration. This may be through a virtual model 
   virtual model, 
   or by  placing the actual prediction into the model column.
   
   When savemodel=’modelcolumn’ is chosen, the message, “Saving model column” will appear in the logger
   during the last major cycle. The model will be written to MODEL_DATA column of the main table of the MS
   for relevant field and spw(s). Similarly, with savemodel=‘virtual’, the message, "Saving virtual model" will appear in the logger.
   In the case of the virtual model, the model parameters are saved in a keyword of the main table in the MS or in SOURCE subtable.
   SOURCE subtable is an optional table and if it exists and containing non-zero number of rows, the model parameters are written to SOURCE_MODEL 
   column in the row for the corresponding SOURCE ID.
   When the virtual model is stored in the keyword of the MS, they are stored with key name such as ‘model_0’. 
   In the case of multiple models exist, say for multiple fields, one can associate particular model key name with a specific field id 
   by looking up the key, ‘definedmodel_field_#’, where # is the field id. 
   Additional information is avaialbe at Virtual Model Visibilities.
   
   To check if model visibility data is present in the MS, ::
          
          tb.open('xxx.ms')
          tb.colnames()  # will show MODEL_DATA in the the returned column names if MODEL_DATA column exists
          tb.keywordnames() # if you see, definedmodel_field_{fieldid}, there is a virtual model exists for the field 
          # Also the model parameters (e.g. for 'model_0') can be retrieved by
          mymodel=tb.getkeyword('model_0')
          tb.done()
         
          # If SOURCE is listed in the keywordnames listing in the above command, and if SOURCE has non-zero rows, virtual model(s) 
          # may exist in SOURCE_MODEL column of SOURCE, 
          # e.g. to get a virutal model for field id=0 (source id=0)
          tb.open('xxx.ms/SOURCE')
          mymodel=tb.getcell('SOURCE_MODEL',0)   # note that since the model parameter are stored in the record (Python dictionaruy)tb.getcol cannot be used)
          tb.done()
          
   To check the content of the model data ( either from MODEL_DATA or virutal model generated on the fly), ::
   
          plotms(vis=‘xxx.ms’, field=‘your_field_that_model_expected_to_be_stored’, spw=.., xaxis=‘uvidist’, yaxis=‘amp’,ydatacolumn=‘model’)
          
 

   
   .. warning:: Please note that tclean may be safely interrupted using a Ctrl-C at all times except when it is in the middle of writing the model data column during a major cycle. To avoid concerns about corrupting your MS by trying to interrupt tclean during a disk write, please run image-reconstruction and model-saving in two separate steps, with model writing turned off during the iterative image reconstruction step. 
      For example: ::
      
          tclean(vis='xxx.ms', imagename='try',......., niter=20,savemodel='none')
          tclean(vis='xxx.ms', imagename='try',...., niter=0, savemodel='modelcolumn', calcpsf=False, calcres=False, restoration=False)
      
      This sequence will show a message in the logger that says "Saving Model Column". Note that while this "predict-only" major cycle is ongoing, Ctrl-C should not be used. 

   
   -  .. rubric:: PB-Correction:
   
   Divide out the Primary Beam from the restored Sky image.
