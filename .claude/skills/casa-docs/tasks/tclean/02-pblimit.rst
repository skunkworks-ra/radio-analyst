   
   .. rubric:: pblimit
   
   The pblimit is a parameter used to define the value of the
   antenna primary beam gain, below which wide-field gridding
   algorithms such as *'mosaic'*, *'awproject'* and *'awp2'* will not apply
   normalization (and will therefore set to zero).  For
   *gridder='standard'*, *'wproject'* , *'widefield'* there is no pb-based 
   normalization during gridding and so the absolute value of 
   this parameter is ignored.

   The sign of the pblimit parameter is used for a different
   purpose. If positive, it defines a T/F pixel mask that is
   attached to the output residual and restored images.  If
   negative, this T/F pixel mask is not included. For the *'mosaic'*, 
   *'awproject'*, and *'awp2'* gridders, the zeros in the regions outside the 
   absolute pblimit level will be visible without the T/F mask, and 
   for other gridders that do not do any pblimit-based normalizations
   (*'standard'*, *'wproject'*, *'widefield'*) those regions will 
   contain valid image pixels.
   
   Please note that this pixel mask is different from the deconvolution 
   mask used to control the region where CLEAN based algorithms will search
   for source peaks.  In order to set a deconvolution mask based on pb
   level, please use the *'pbmask'* parameter.
   
   .. warning:: Certain values of pblimit should be avoided!
      These values are 1, -1, and 0. Details can be found
      here.
   
   .. rubric:: widebandpbcor
   
   Widebandpbcor
   is a separate task, and will eventually be implemented as a
   parameter in **tclean**. It allows correction of the primary beam
   as part of wideband
   imaging.
   It computes a set of PBs at the specified frequencies, calculates
   Taylor-coefficient images that represent the PB spectrum, performs
   a polynomial division to PB-correct the output Taylor-coefficient
   images from **tclean** (with *nterms>1* and
   *deconvolver='mtmfs'*), and recomputes the spectral index (and
   curvature) using the PB-corrected Taylor-coefficient images.
   
   -  .. rubric:: Pointing Corrections:
   
   Heterogeneous Pointing Corrections can optionally be applied with
   the *usepointing* and *pointingoffsetsigdev* parameters. These
   parameters apply corrections based on the pointing errors that are
   present in the POINTING sub-table. This can improve imaging
   performance for observations with high wide-band sensitivity, such
   as is typically observed with the VLA and ALMA telescopes. An
   overview of pointing corrections is given in the CASA Docs page on
   Widefield
   Imaging.
   
   -  .. rubric:: Restoration:
   
   Specify a restoring beam and re-restore the model image.
   
   -  .. rubric:: Auto-masking:
   
   Automatically mask emission during clean; see Masks for
   Deconvolution
   for more information.
