


   .. rubric:: CURSOR AXES

   The *axes* parameter allows one to set the cursor axes over
   which statistics are computed. For example, consider a
   3-dimensional image for which *axes=[0,2]*. The statistics would
   be computed for each XZ (axes 0 and 2) plane in the image. One
   could then examine those statistics as a function of the Y (axis
   1) axis.
   Each statistic is stored in an array in its own field in the
   returned dictionary. The dimensionality of these arrays is equal
   to the number of axes over which the statistics were not
   evaluated (called the display axes). For example, if the input
   image has four axes, and *axes=[0]*, the output statistic arrays
   will have three dimensions. If *axes=[0, 1]*, the output
   statistic arrays will have two dimensions.
   The shape of the output arrays when axes has a positive number
   of elements is based on the region selection. If there is no
   region selection, the shape of the statistic arrays is just the
   shape of the image along the display (non-cursor) axes. For
   example, if the input image has dimensions of 300x400x4x80 (RA x
   Dec x Stokes x Freq) and *axes=[0, 1]*, in the absence of a
   region selection, the shape of the output statistic arrays will
   be 4x80. If there is a region selection, the shape of the output
   statistic arrays will be determined by the number of planes
   along the display axes chosen in the region selection. For
   example, continuing with our example, if *axes=[0,1]*,
   *chans="5~15;30~70"*, and *stokes="IV"*, the output statistic
   arrays will have shapes of 2x52. Only the selected planes will
   be displayed in the logger output if *verbose=True*.
   In the case where the image has a pixel mask, and/or the *mask*
   parameter is specified, and because of this specification a
   plane is entirely masked, this element is included in the
   statistic arrays (usually with a value of 0). It is not included
   in the logger output if *verbose=True*. One can exclude such
   elements from computations on the output arrays by using the
   numpy.extract() method. For example, to compute the minimum rms
   value, not including any fully masked planes, one could use

   ::

      stats = imstat(...)
      rmsmin = numpy.min(numpy.extract(stats['npts']>0,
      stats['rms']))

   Thus in the computation of rmsmin, only the rms elements are
   considered which have associated values of 'npts' that are greater
   than zero.


   .. rubric:: ALGORITHMS

   Several types of statistical algorithms are supported:

   .. rubric:: CLASSIC

   This is the familiar algorithm, in which all unmasked pixels are
   used. One may choose one of two methods, which vary only by
   performance, for computing classic statistics via the *clmethod*
   parameter. The "tiled" method is the old method and is fastest in
   cases where there are a large number of individual sets of
   statistics to be computed and a small number of data points per
   set. This can occur when one sets the *axes* parameter, which
   causes several individual sets of statistics to be computed. The
   "framework" method uses the new statistics framework to compute
   statistics. This method is fastest in the regime where one has a
   small number of individual sets of statistics to calculate, and
   each set has a large number of points. For example, this method is
   fastest when computing statistics over an entire image in one go
   (no *axes* specified). A third option, "auto", chooses which
   method to use by predicting which be faster based on the number of
   pixels in the image and the choice of the *axes* parameter.

   .. rubric:: FIT-HALF

   This algorithm calculates statistics on a dataset created from
   real and virtual pixel values. The real values are determined by
   the input parameters *center* and *lside*. The parameter *center*
   tells the algorithm where the center value of the combined
   real+virtual dataset should be. Options are the mean or the median
   of the input image's pixel values, or at zero. The *lside*
   parameter tells the algorithm on which side of center the real
   pixel values are located. True indicates that the real pixel
   values to be used are ≤ center. False indicates the real pixel
   values to be used are ≥ center. The virtual part of the dataset is
   then created by reflecting all the real values through the center
   value, to create a perfectly symmetric dataset composed of a real
   and a virtual component. Statistics are then calculated on this
   resultant dataset. These two parameters are ignored if algorithm
   is not "FIT-HALF". Because the maximum value is virtual if *lside*
   is True and the minimum value is virtual if *lside* is False, the
   value of the maximum position (if *lside=True*) or minimum
   position (if *lside=False*) is not reported in the returned
   record.

   .. rubric:: HINGES-FENCES

   This algorithm calculates statistics by including data in a range
   between :math:`Q1 - f*D` and :math:`Q3 + f*D`, inclusive, where Q1
   is the first quartile of the distribution of unmasked data,
   subject to any specified pixel ranges, Q3 is the third quartile,
   :math:`D = Q3 - Q1` (the inner quartile range), and f is the
   user-specified fence factor. Negative values of f indicate that
   the full distribution is to be used (i.e., the classic algorithm
   is used). Sufficiently large values of f will also be equivalent
   to using the "CLASSIC" algorithm. For f = 0, only data in the
   inner quartile range is used for computing statistics. The value
   of fence is silently ignored if algorithm is not "HINGES-FENCES".
