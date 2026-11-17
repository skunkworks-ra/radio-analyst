   
   .. rubric:: Task-specific Parameter Descriptions
   
   *includepix*
   
   Two element array giving the range of pixel values to include in
   the fit. Only one range of pixel values may be specified in
   includepix or excludepix.
   
   *excludepix*
   
   Two element array giving the range of pixel values to exclude in
   the fit. Only one range of pixel values may be specified in
   includepix or excludepix.
   
   *residual*
   
   Name of output residual image. Empty string indicates that the
   residual image should not be written.
   
   *model*
   
   Name of output model image. Empty string indicates that the model
   image should not be written.
   
   *estimates*
   
   Name of the text file that contains the initial parameter
   estimates. See the above description describing the format for
   such a file. An empty string indicates that the application should
   automatically determine initial parameter estimates. If it is
   desired that more than one Gaussian be fit simultaneously, an
   estimates file must be specified.
   
   *logfile*

   Name of output file to which to write results. If set to the empty
   string, no logfile is written, although the results can still be
   obtained from the logger output.
   
   *append*
   
   If True, append results to the specified logfile if it already
   exists. If False, overwrite an existing logfile if it already
   exists.
   
   *newestimates*
   
   Name of file to which to write the results of the fit in an
   estimates file format, so that the written file can be used as the
   estimates file on subsequent runs. The empty string means do not
   write such a file.
   
   *complist*
   
   Name of the component list table to which to write the fitted
   model. The empty string indicates that a component list table
   should not be written.
   
   *overwrite*
   
   Indicates if an existing component list table should be
   overwritten. If False and a component list table of the name
   specified by the complist parameter already exists, an exception
   will be thrown.
   
   *dooff*
   
   Indicates if a constant zero-level offset should also be
   simultaneously fit.
   
   *offset*
   
   Initial estimate for the zero level offset, in the same units as
   the values in the image.
   
   *fixoffset*
   
   Indicates if the specified zero-level offset should be held fixed
   during the fit.
   
   *rms*
   
   RMS to use in calculation of uncertainties. Numeric or valid
   quantity (record or string). If numeric, it is given units of the
   input image. If quantity, units must conform to image units. If
   not positive, the rms of the residual image, in the region of the
   fit, is used. See the above discussion for more details.
   
   *noisefwhm*
   
   Noise correlation beam FWHM. If numeric value, interpreted as
   pixel widths. If quantity (dictionary, string), it must have
   angular units. See the above discussion for more details.
   
   *summary*
   
   Name of file to which to write a plain text table summary of the
   fit parameters. The empty string indicates that such a file should
   not be written.
   
   
   .. rubric:: Bibliography

   .. [1] Condon (1997) `http://adsabs.harvard.edu/abs/1997PASP..109..166C <http://adsabs.harvard.edu/abs/1997PASP..109..166C>`__
