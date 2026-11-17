

   .. rubric:: Important Note About Flux Conservation

   In general, regridding is inaccurate for images in which the
   angular resolution is poorly sampled.

   The issue is that CASA treats the values in "pixels" as
   measurements of a sky brightness distribution, each at an
   infinitessimally small single point at the location of the "pixel"
   center (to enable the Fourier transforms and gridding that CASA
   deals with regularly). If one has well-sampled the (beam-smoothed)
   sky brightness distribution, then one can resample that
   distribution to a different set of locations, and everything will
   come out correctly. If one has not sampled the distribution well,
   then interpolation to other locations will introduce significant
   errors. Imagine a worst case of a (well-sampled) peak being
   resampled to large "pixel" locations, such that the centers of
   two output pixels fall on either side of the peak. The
   interpolated values at those locations will effectively cause the
   peak to completely disappear.

   This is in contrast to software that considers the value in a
   "pixel" to be the sum of the sky brightness subtended by that
   finite-sized pixel. In such software, resampling to other pixels
   requires calculating the overlap of the old and new finite-sized
   pixels, and apportioning the summed flux among output pixels
   accordingly. Such an operation is designed to conserve the total
   flux in the image even if the beam is not well-sampled and is
   common in most optical and infrared imaging and display software.
   Again considering the pathological example of a peak being sampled
   onto a large-pixel grid, explicitly flux-conserving software would
   add up the values from all of the small input pixels, and thus
   although the peak would be coarsely represented in the output
   image, the flux from that peak would not disappear.

   In CASA, the different definition of what a "pixel" is requires
   that one have a well-sampled beam, or one will inherently not get
   the right answer. A check is done for such cases and a warning
   message is printed if a beam is present. However, no such check is
   done if there is no beam present. To add a restoring beam to an
   image, use **ia.setrestoringbeam**.


   .. rubric:: Task-specific Parameter Summary

   *template*

   Indicates how the template coordinate system is being specified.
   See above for details.

   *shape*

   Shape of the output image. Only used if template is an image. If
   not specified (-1), the output image shape will be the same as the
   template image shape along the axes that are regridded and the
   same as input image shape along the axes which  are not regridded.

   *asvelocity*

   Regrid spectral axis in velocity space rather than frequency
   space?

   *axes*

   The pixel axes to regrid. -1 => all.

   *interpolation*

   The interpolation method. One of "nearest", "linear", "cubic".

   *decimate*

   Decimation factor for coordinate grid computation. A value of 10
   is sufficient in most cases, except for images in which the length
   of at least one axis to be regridded is less than about 70 or if
   the input or output direction coordinate is close to a pole. In
   these cases, a smaller factor will give signficantly better
   accuracy.

   *replicate*

   Replicate image rather than regrid?
