

.. _Returns:

Returns
   stats (dict) - image statistics computed over given axes


.. _Description:

Description
   .. warning:: There are Known Issues for imstat.

   Many parameters are determined from the specified region of an
   image. The region can be specified by a set of rectangular pixel
   coordinates, the channel ranges and the
   Stokes or a region file.

   .. warning:: **Alert:** When both the *region* parameter and any of
      *box*/*chans*/*stokes* are specified simultaneously, the task
      may perform unwanted selections, so this should be avoided. See
      this chapter on region files
      for more information.

   For directed output, run as:

   ::

      myoutput=imstat()

   General procedure:

   ::

      #Specify inputs, then
      myoutput=imstat()

      # or specify inputs directly in calling sequence to task
      myoutput=imstat(imagename='image.im', etc)
      myoutput['KEYS']   # will contain the result associated with any of the keys given below


   +-----------------------------------+-----------------------------------+
   | KEYS                              | DESCRIPTION                       |
   +-----------------------------------+-----------------------------------+
   | blc                               | absolute PIXEL coordinate of the  |
   |                                   | bottom left corner of the         |
   |                                   | bounding box surrounding the      |
   |                                   | selected region                   |
   +-----------------------------------+-----------------------------------+
   | blcf                              | Same as blc, but uses WORLD       |
   |                                   | coordinates instead of pixels     |
   +-----------------------------------+-----------------------------------+
   | trc                               | the absolute PIXEL coordinate of  |
   |                                   | the top right corner of the       |
   |                                   | bounding box surrounding the      |
   |                                   | selected region                   |
   +-----------------------------------+-----------------------------------+
   | trcf                              | Same as trc, but uses WORLD       |
   |                                   | coordinates instead of pixels     |
   +-----------------------------------+-----------------------------------+
   | flux                              | the flux or flux density. See     |
   |                                   | below for details.                |
   +-----------------------------------+-----------------------------------+
   | npts                              | the number of unmasked points     |
   |                                   | used                              |
   +-----------------------------------+-----------------------------------+
   | max                               | the maximum pixel value           |
   +-----------------------------------+-----------------------------------+
   | min                               | minimum pixel value               |
   +-----------------------------------+-----------------------------------+
   | maxpos                            | absolute PIXEL coordinate of      |
   |                                   | maximum pixel value               |
   +-----------------------------------+-----------------------------------+
   | maxposf                           | Same as maxpos, but uses WORLD    |
   |                                   | coordinates instead of pixels     |
   +-----------------------------------+-----------------------------------+
   | minpos                            | absolute pixel coordinate of      |
   |                                   | minimum pixel value               |
   +-----------------------------------+-----------------------------------+
   | minposf                           | Same as minpos, but uses WORLD    |
   |                                   | coordinates instead of pixels     |
   +-----------------------------------+-----------------------------------+
   | sum                               | the sum of the pixel              |
   |                                   | values: :math:`\sum I_i`          |
   +-----------------------------------+-----------------------------------+
   | sumsq                             | the sum of the squares of the     |
   |                                   | pixel values: :math:`\sum I_i^2`  |
   +-----------------------------------+-----------------------------------+
   | mean                              | the mean of pixel                 |
   |                                   | values                            |
   |                                   | : :math:`\bar{I} = \sum I_i / n`  |
   +-----------------------------------+-----------------------------------+
   | sigma                             | the standard deviation about the  |
   |                                   | mean: :math:`\sigma^2             |
   |                                   | = (\sum I_i - \bar{I})^2 / (n-1)` |
   +-----------------------------------+-----------------------------------+
   | rms                               | the root mean                     |
   |                                   | square                            |
   |                                   | : :math:`\sqrt {\sum I_i^2 / n}`  |
   +-----------------------------------+-----------------------------------+
   | median                            | the median pixel value            |
   +-----------------------------------+-----------------------------------+
   | medabsdevmed                      | the median of the absolute        |
   |                                   | deviations from the median        |
   +-----------------------------------+-----------------------------------+
   | quartile                          | the inner-quartile range. Find    |
   |                                   | the points which are 25% largest  |
   |                                   | and 75% largest (the median is    |
   |                                   | 50% largest).                     |
   +-----------------------------------+-----------------------------------+
   | q1                                | the first quartile                |
   +-----------------------------------+-----------------------------------+
   | q3                                | the third quartile                |
   +-----------------------------------+-----------------------------------+
