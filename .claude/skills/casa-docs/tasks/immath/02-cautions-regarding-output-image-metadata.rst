   
   .. rubric:: CAUTIONS REGARDING OUTPUT IMAGE METADATA
   
   EXCEPT IN THE EXAMPLES GIVEN HERE, THIS APPLICATION MAKES NO
   ATTEMPT TO DETERMINE WHAT THE CORRECT BRIGHTNESS UNIT OF THE
   OUTPUT IMAGE SHOULD BE. THIS RESPONSIBILITY LIES SOLELY WITH THE
   USER. The brightness unit of the output image can be modified
   using tool method **ia.setbrightnessunit** or task **imhead** with
   *mode='put'* and *hdkey='bunit'*.
   
   Note that when multiple image are used in the expression, there is
   no strict rule which of those images will be used to create the
   metadata of the output image, unless imagemd is specified. If
   *imagemd* is specified, the following rules of metadata copying
   will be followed:
   
   #. The pixel data type of the image specified by *imagemd* and the
      output image must be the same.
   #. The metadata copied include
   
      -  the coordinate system - thus, the dimensionality of the
         output image must correspond to the coordinate system to be
         copied
      -  the image_info record - which contains information like the
         beam(s)
      -  the misc_info record - if one exists in the image specified
         by *imagemd*
      -  the units.
   
   #. If the output image is a spectral index image, the brightness
      units are set to the empty string.
   #. If the ouptut image is a polarization angle image, the
      brightness unit is set to "deg" and the stokes coordinate is
      set to have a single plane of type of Pangle.

   
   .. rubric:: TEMPORARY IMAGES
   
   It is often necessary for this task to create intermediate,
   temporary disk images. The names of these images start with
   '_immath' and are created in the directory in which the task is
   run. The task makes reasonable attempts to remove these images
   before it exits, but there are conceivably instances where the
   temporary images may not be automatically deleted. If there is no
   immath instance in progress, it is generally safe to delete these
   files manually.

   
   .. rubric:: Task-specific Parameter Summary
   
   *mode*
   
   Mode of operation. Supported values are *'evalexpr'* (evaluate an
   LEL expression), *'spix'* (spectral index computation, although
   see also task **spxfit** for a more robust algorithm), *'pola'*
   (polarization angle), and *'poli'* (total polarization intensity).
   
   *expr*
   
   Used when *mode='evalexpr'*. LEL expression to compute.
   
   *varnames*

   List of normally short strings corresponding to the images given
   in imagename that can alternatively be used for the image names
   given in expr when *mode='evalexpr'*.
   
   *sigma*
   
   Used if *mode = 'poli'*. Standard deviation of noise for
   debiasing.
   
   *polithresh*

   Used if *mode = 'pola'*. Threshold in linear polarization
   intensity image below which to mask pixels.
   
   *imagemd*

   Name of image from which metadata should be copied to the output
   image. The input can be either an image listed in the imagename
   parameter or any other image on disk. Not specifying this
   parameter may copy header metadata from any of the input images,
   which one is not guaranteed.
   
   *prec*
   
   Specifies what the precision type, float or double (minimum match
   supported), should be for the output image. Only used if
   mode='evalexpr' or 'spix'.
