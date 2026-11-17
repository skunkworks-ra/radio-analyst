

.. _Description:

Description
   .. warning:: There are Known Issues for imregrid.

   This task will regrid an input image onto a new coordinate system
   from a template image or to a new directional and spectral
   reference frame. If a template image is used, then the input and
   template images must have the same coordinate structure. The
   **imregrid** task currently finds the nearest input pixel center
   and interpolates to the output pixel center.

   .. warning:: No averaging is done in any direction!


   .. warning:: PV images are not supported. Please first regrid as
      desired the image from which the PV image was generated, and
      then create the PV image from that regridded image.


   The new coordinate system is defined by the *template* parameter,
   which can be:

   -  a recognized directional reference frame string. Supported
      case-insensitive values are 'J2000', 'JMEAN', 'JTRUE', 'APP',
      'B1950', 'B1950_VLA', 'BMEAN', 'BTRUE', 'GALACTIC', 'HADEC',
      'AZEL', 'AZELSW', 'AZELNE', 'AZELGEO', 'AZELSWGEO', 'AZELNEGEO',
      'JNAT', 'ECLIPTIC', 'MECLIPTIC', 'TECLIPTIC', 'SUPERGAL', 'ITRF',
      'TOPO', and 'ICRS'. Note that the conversion between one frame
      and another in general becomes less accurate as distance from
      the output image's reference pixel increases. After the image
      is regridded, any masked slices remaining along the edges of
      the image in the directional coordinate are cropped, so that
      there are no masked slices in the directional coordinate along
      the edges of the final image. Note that some direction
      coordinate projections, such as SFL often found in GBT images,
      have constraints which do not allow for simple regridding of
      the direction coordinate. The application will throw an
      exception in these cases.
   -  a {'csys':[valid coordinate system dictionary], 'shap':[int
      array describing the output shape]} dictionary. This is
      normally obtained by first running regrid with
      *template='get'*. In this case **imregrid** returns the
      necessary dictionary.
   -  'get', which does not regrid but returns the template
      dictionary for *imagename*, suitable for modification and reuse
      (see the point immediately above), or
   -  the name of an image from which to get the coordinate system
      and shape. The input and template images must have the same
      coordinate structure.

   Regridding of complex-valued images is supported. The real and
   imaginary parts are regridded independently and the resulting
   regridded pixel values are combined to form the regridded,
   complex-valued image.

   The *replicate* parameter can be used to simply replicate pixels
   rather than regridding them. Normally, *replicate=False*, for
   every output pixel, its world coordinate is computed and the
   corresponding input pixel found (then a little interpolation grid
   is generated). If you set *replicate=True*, then what happens is
   that for every output axis, a vector of regularly sampled input
   pixels is generated (based on the ratio of the output and input
   axis shapes). So this just means the pixels get replicated (by
   whatever interpolation scheme you use) rather than regridded in
   world coordinate space. This process is much faster, but its not a
   true world coordinate-based regrid.

   As decribed above, when *replicate* is False, a coordinate is
   computed for each output pixel; this is an expensive operation.
   The *decimate* parameter allows you to decimate the computation of
   that coordinate grid to a sparse grid, which is then filled in via
   fast interpolation. The default for *decimate* is 10. The number
   of pixels per axis in the sparse grid is the number of output
   pixels for that axis divided by the decimation factor. A factor of
   10 does pretty well. You may find that for very non-linear
   coordinate systems (e.g. very close to the pole) that you have to
   reduce the decimation factor. You may also have to reduce the
   decimation factor if the number of pixels in the output image
   along an axis to be regridded is less than about 50, or the output
   image may be completely masked.

   If one of the axes to be regridded is a spectral axis and
   *asvelocity=True*, the axis will be regridded to match the
   velocity, not the frequency, coordinate of the template coordinate
   system. Thus the output pixel values will correspond only to the
   velocity, not the frequency, of the output axis.

   A variety of `standard interpolation
   schemes <https://en.wikipedia.org/wiki/Interpolation>`__ are
   provided (only the first three characters to be specified). The
   'cubic' interpolation is substantially slower than 'linear', and
   often the improvement is modest. By default 'linear' interpolation
   is used.

   If an image has per-plane beams and one attempts to regrid the
   spectral axis, an exception is thrown. One should consider
   convolving all planes to the same resolution in such cases and
   then regridding.

   .. rubric:: Rules Used for Generating Output Images in Specific Cases

   There are numerous rules governing the shape and coordinate system
   of the output image depending on the input image, template image,
   and wheher default values of the axes and shape parameters are
   used. They are enumerated below.

   .. note:: **NOTE**: If you want to be certain of what type of output you
      will get, it is highly recommended you specify both axes and
      shape to avoid any ambiguity.
