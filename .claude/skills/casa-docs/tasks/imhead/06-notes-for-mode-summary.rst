
   
   .. rubric:: Notes for *mode='summary'*
   
   If *mode='summary'*, various metadata will be listed to the
   logger, and a dictionary containing some metadata will be
   returned. The key/value pairs in the returned dicitonary will be:
   
   +---------------+-----------------------------------------------------+
   | **Values**    |  **Description**                                    |
   +---------------+-----------------------------------------------------+
   | axisnames     | Array of image axes names.                          |
   +---------------+-----------------------------------------------------+
   | axisunits     | Array of image axes units.                          |
   +---------------+-----------------------------------------------------+
   | defaultmask   | name of the default mask. The empty string          |
   |               | indicates the image has no default mask.            |
   +---------------+-----------------------------------------------------+
   | hasmask       | Boolean value indicating if the image has a mask.   |
   +---------------+-----------------------------------------------------+
   | imagetype     | String describing what the image pixels represent.  |
   |               | Possible values are: *'Intensity', 'Beam', 'Column  |
   |               | Density', 'Depolarization Ratio', 'Kinetic          |
   |               | Temperature', 'Magnetic Field', 'Optical Depth',    |
   |               | 'Rotation Measure', 'Rotation Temperature',         |
   |               | 'Spectral Index', 'Velocity', 'Velocity             |
   |               | Dispersion', and 'Undefined'*.                      |
   +---------------+-----------------------------------------------------+
   | incr          | Array of axes increments, in axes units.            |
   +---------------+-----------------------------------------------------+
   | masks         | Array of all mask names associated with the image.  |
   +---------------+-----------------------------------------------------+
   | messages      | Currently unused. Will always be the empty string.  |
   +---------------+-----------------------------------------------------+
   | ndim          | number of dimensions for the image.                 |
   +---------------+-----------------------------------------------------+
   | perplanebeams | Dictionary of per-plane beams. Only present if the  |
   |               | image has per-plane beams.                          |
   +---------------+-----------------------------------------------------+
   | refpix        | Array of numerical values indicating the image axes |
   |               | reference pixels.                                   |
   +---------------+-----------------------------------------------------+
   | refval        | Array of numerical values indicating the reference  |
   |               | values of the axes in axes units.                   |
   +---------------+-----------------------------------------------------+
   | restoringbeam | The image restoring beam, only present if the the   |
   |               | image has a single, global restoring beam.          |
   +---------------+-----------------------------------------------------+
   | shape         | Array of integers indicating the number of pixels   |
   |               | on each image axis.                                 |
   +---------------+-----------------------------------------------------+
   | tileshape     | Image tile shape.                                   |
   +---------------+-----------------------------------------------------+
   | unit          | Image brightness unit.                              |
   +---------------+-----------------------------------------------------+
   
    
   
   .. rubric:: Task-specific Parameters Summary

   *mode*
   
   Mode of operation. See above for details. Modes which involve
   writing parameters will fail on read-only images, such as FITS
   images.
   
   *hdkey*
   
   The associated keyword for modes *"add"*, *"del"*, *"get"*, or
   *"put"*. Only *mode="get"* will succeed for read-only images. See
   above for supported values.
   
   *hdvalue*
   
   Value of keyword used only for modes add or put.
   
   *verbose*
   
   Give a full listing of beams or just a short summary? Only used
   when the image has multiple beams and *mode="summary"*.
