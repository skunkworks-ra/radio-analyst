

   .. rubric:: *1. Rules governing Stokes axes*

   1.1. If the input image has no stokes axis, then the output
   image will have no stokes axis.

   1.2. If the input image has a stokes axis, but the template
   image/coordinate system does not, and if the default value of the
   *shape* parameter is used or if *shape* is specified and the
   specified value for the length stokes axis in equal to the length
   of the input image stokes axis, then all stokes in the input image
   will be present in the output image.

   1.3. If the input image has a stokes axis, but the template
   image/coordinate system does not, and if the value of the *shape*
   parameter is specified but the length of the resulting stokes axis
   is not equal to the length of the input image's stokes axis, a
   failure will occur.

   1.4. If the input image has a stokes axis, if the *template*
   parameter is an image name, and if the template image has a
   degenerate stokes axis, if the *axes* parameter is not specified
   or is specified but does not contain the input stokes axis number,
   and if the *shape* parameter is not specified, then all stokes
   planes in the input image will be present in the output image.

   1.5. If the input image has a stokes axis, if the *template*
   parameter is an image name, and if the template image has a
   degenerate stokes axis, if the *axes* parameter is not specified
   or is specified but does not contain the input stokes axis number,
   if the *shape* parameter is specified, and if the specified length
   of the stokes axis is not equal to the length of the input stokes
   axis, then a failure will occur.

   1.6. If the input image has a stokes axis, if the *template*
   parameter is an image name, if the template image has a degenerate
   stokes axis, if the *axes* parameter is specified contains the
   input stokes axis number, then use the applicable rule of rules
   1.7. and 1.8. for the template image having a nondegenerate stokes
   axis.

   1.7. If the input image has a stokes axis, if the *template*
   parameter is an image name, if the template image has a
   nondegenerate stokes axis, and if *axes* parameter is not
   specified or if it is, it contains the input stokes axis number,
   then only the stokes parameters common to both the input image and
   the template image will be present in the output image. If the
   input image and the template image have no common stokes
   parameters, failure will occur. If shape is specified and the
   length of the specified stokes axis is not equal to the number of
   common stokes parameters in the input image and the template
   image, then failure will result.

   1.8. If the input image has a stokes axis, if the *template*
   parameter is an image name, if the template image has a
   nondegenerate stokes axis, and if *axes* parameter is specified
   but does not contain the input image stokes axis number, then all
   stokes present in the input image will be present in the output
   image. If the *shape* parameter is also specified but the length
   of the specified stokes axis does not equal the length of the
   input stokes axis, then failure will result.


   .. rubric:: *2. Rules governing spectral axes*

   In all cases, if the shape *parameter* is specified, the spectral
   axis length must be consistent with what one would normally expect
   in the special cases, or a failure will result.

   2.1. If the input image does not have a spectral axis, then
   the output image will not have a spectral axis.

   2.2. If the input image has a degenerate spectral axis, if the
   *template* parameter is an image name, and if the template image
   has a spectral axis, if the *axes* parameter is not specified or
   if it is and does not contain the input image spectral axis
   number, then the spectral coordinate of the input image is copied
   to the output image and the output image will have a degenerate
   spectral axis.

   2.3. If the input image has a degenerate spectral axis, if the
   *template* parameter is an image name, and if the template image
   has a spectral axis, if the *axes* parameter is specified and it
   contains the input image spectral axis number, then the spectral
   coordinate of the template image is copied to the output image. If
   the *shape* parameter is not specified, the output image will have
   the same number of channels as the input image. If the *shape*
   parameter is specified, the output image will have the number of
   channels as specified in shape for the spectral axis. In these
   cases, the pixel and mask values for all spectral hyperplanes will
   be identical; the regridded single spectral plane is simply
   replicated n times, where n is the number of channels in the
   output image.

   2.4. If the input image has a spectral axis, if the *template*
   parameter is an image name, and if the template image does not
   have a spectral axis, if the *axes* parameter is not specified or
   if it is and does not contain the input image spectral axis
   number, then the spectral coordinate of the input image is copied
   to the output image and the output image will have the same number
   of channels as the input image.

   2.5. If the input image has a spectral axis, if the *template*
   parameter is an image name, if the template image does not have a
   spectral axis, if the *axes* parameter is specified and it
   contains the input image spectral axis number, then failure will
   result.

   2.6. If the input image has a spectral axis, if the *template*
   parameter is an image name, if the template image has a degenerate
   spectral axis, and if the *axes* parameter is unspecified or if it
   is but does not contain the spectral axis number of the input
   image, the spectral coordinate of the input image is copied to the
   output image and the output image will have the same number of
   channels as the input image.

   2.7. If the input image has a spectral axis, if the *template*
   parameter is an image name, if the template image has a
   nondegenerate spectral axis, and if the *axes* parameter is
   unspecified or if it is and contains the spectral axis number of
   the input image, regrid the spectral axis of the input to match
   the spectral axis of the template.
