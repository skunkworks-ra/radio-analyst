

.. _Returns:

Returns
   stats (dict) - mean and variance of the weights computed


.. _Description:

Description
   .. warning:: There is a Known Issues for statwt: If not run in preview mode, this application can
      modify the WEIGHT, WEIGHT_SPECTRUM, SIGMA, SIGMA_SPECTRUM,
      FLAG, and FLAG_ROW columns of the input MS. If you want a
      pristine copy of the input MS to be preserved, you should make
      a copy of it before running this application.
   
   This application computes values for the WEIGHT and
   WEIGHT_SPECTRUM (if present) columns and/or the SIGMA and
   SIGMA_SPECTRUM (if present) columns based on the variance of
   values in the CORRECTED_DATA or DATA column. If the MS does not
   have the specified data column, the application will fail. The
   following algorithm is used:
   
   #. For unflagged data in each sample, create two sets of values,
      one set is composed solely of the real part of the data values,
      the other set is composed solely of the imaginary part of the
      data values.
   #. Compute the weighted (by exposure time) variance of each of
      these sets, v :math:`_r` and v :math:`_i`. The weighted
      variance per unit inverse exposure time, v, is computed using v
      = sum(e :math:`_i` \* (V :math:`_i` - <V>) :math:`^2`)/N,
      where e :math:`_i` is the exposure time for real/imaginary
      part of  visibility V :math:`_i` and <V> = sum(e :math:`_i`
      \* V :math:`_i`)/sum(e :math:`_i`) is the weighted mean of
      all the visibilities in the set, and N is the number of
      (unflagged) visibilities (see also this Knowledgebase
      Article)
   #. Compute v :math:`_{eq}` :math:`=` (v :math:`_{r}` :math:`+`
      v :math:`_{i}`) :math:`/` 2.
   #. The associated weight of visibility V :math:`_i`  is 
      e :math:`_i` / V (see Knowledgebase
      Article).
      The weight will have unit of (data unit), e.g., Jy. The
      visibility weights are what this application computes and
      writes.
   
   Data are aggregated on a per-baseline, per-data description ID
   basis. Data are aggregated in bins determined by the specified
   values of the timebin and chanbin parameters. By default, data for
   separate correlations are aggregated separately. This behavior can
   be overriden by specifying combine="corr" (see below).
   
   .. rubric:: Rules regarding creating/initializing WEIGHT_SPECTRUM column
   
   #. If run in preview mode (preview=True), no data are modified and
      no columns are added.
   #. Else if datacolumn='residual' or 'residual_data' and a
      CORRECTED_DATA column exists, the WEIGHT and WEIGHT_SPECTRUM
      columns are not modified.
   #. Else if the MS already has a WEIGHT_SPECTRUM and this column
      has been initialized (has values) it will always be populated
      with the new weights. The WEIGHT column will be populated with
      the corresponding median values of the associated
      WEIGHT_SPECTRUM array.
   #. Else if the frequency interval (chanbin) is not the default
      ('spw', not to be confused with the parameter spw), the
      WEIGHT_SPECTRUM column will be created (if it doesn't already
      exist) and the new weights will be written to it. The WEIGHT
      column should be populated with the corresponding median values
      of the WEIGHT_SPECTRUM array.
   #. Otherwise the single value for each spectral window will be
      written to the WEIGHT column; the WEIGHT_SPECTRUM column will
      not be added if it doesn't already exist, and if it does, it
      will remain uninitialized (no values will be written to it).
   #. In cases where columns are added and initialized, the
      WEIGHT_SPECTRUM values will be set equal to the corresponding
      WEIGHT values, and the SIGMA_SPECTRUM values will be set to the
      corresponding SIGMA values.
   
   In cases where columns are added and initialized, the
   WEIGHT_SPECTRUM values will be set equal to the corresponding
   WEIGHT values, and the SIGMA_SPECTRUM values will be set to the
   corresponding SIGMA values.
   
   .. warning:: WARNING: For some cases when only a subset of data is selected
      and the WEIGHT_SPECTRUM and/or SIGMA_SPECTRUM columns are
      created, there is a known code issue in which these columns are
      not properly created and initialized for the specified subset
      of data, although they are properly initialized for the entire
      dataset. In such cases, an exception will be thrown. Because
      the columns are created for the entire dataset, the user simply
      needs to rerun the statwt task using the same parameters and
      the task should complete as expected. Should this condition
      occur when the user is using the ms.statwt() tool method, the
      user should close the ms tool, and then reopen it using the
      same data set and configure the same selection, and rerun
      ms.statwt(). The tool method should then complete as expected.

   
   .. rubric:: Rules for modifying WEIGHT, WEIGHT_SPECTRUM, SIGMA, and SIGMA_SPECTRUM
   
   #. If datacolumn='corrected' or 'residual', then values are
      written to the WEIGHT and WEIGHT_SPECTRUM (if applicable)
      columns only.
   #. If datacolumn='data' or 'residual_data' and the CORRECTED_DATA
      column does not exist, then values are written to the WEIGHT
      and WEIGHT_SPECTRUM (if applicable) columns and values in the
      SIGMA and SIGMA_SPECTRUM are set to
      1/ :math:`\sqrt{\rm {newly\,computed\,weight}}`. If a weight
      value is 0, the corresponding sigma value is -1.
   #. If datacolumn='data' or 'residual_data' and the CORRECTED_DATA
      column does exist, then the WEIGHT and WEIGHT_SPECTRUM columns
      are not updated and values in the SIGMA and SIGMA_SPECTRUM are
      set to 1/ :math:`\sqrt{\rm {newly\,computed\,weight}}`. If a
      weight value is 0, the corresponding sigma value is -1. In this
      case, you should either split out the DATA column and run
      **statwt**, or run with *datacolumn='corrected'* or
      *'residual'* to update WEIGHT/WEIGHT_SPECTRUM. Otherwise the
      data are internally not consistent.
   
   .. note:: NOTE: statwt will produce an error if the measurement set has
      WEIGHT_SPECTRUM and/or SIGMA_SPECTRUM columns for which some
      rows are initialized (have values) and other rows have no data.
      It is recommended to run the initweights task to completely
      initialize these columns if you encounter this error.

   
   .. rubric:: Time Binning
   
   One of two algorithms can be used for time binning. If
   slidetimebin=True, then a sliding time bin of the specified width
   is used. If slidetimebin=False, then block time processing is
   used. The sliding time bin algorithm will generally be both more
   memory intensive and take longer than the block processing
   algorithm. Each algorithm is discussed in detail below.
   
   If the value of timebin is an integer,this value represents the
   number of contiguous, unique time stamps (from the MS TIME column)
   that should be used for averaging.
   
   The timebin parameter can also be specified as a quantity (string)
   that must have time conformant units.
