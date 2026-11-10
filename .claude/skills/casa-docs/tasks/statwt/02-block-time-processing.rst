   
   .. rubric:: Block Time Processing
   
   The data are processed in contiguous time blocks in this case.
   This means that all WEIGHT_SPECTRUM values will be set to the same
   value for all data within the same time bin/channel
   bin/correlation bin (see the section on channel binning and
   description of combine="corr" for more details on channel binning
   and correlation binning).
   
   If timebin is specified as a time quantity (eg, '110s'), then the
   time bins are not necessarily contiguous and are not necessarily
   the same width. The start of a bin is always coincident with a
   value from the TIME column, So for example, if values from the
   TIME column are [20s, 60s, 100s, 140s, 180s, 230s], and timebin =
   110s, the first bin would start at 20s and run to 130s, so that
   data from timestamps 20s, 60s, and 100s will be included in the
   first bin. The second bin would start at 140s, so that data for
   timestamps 140s, 180s, and 230s would be included in the second
   bin.
   
   In the case where timebin is an integer, this denotes the number
   of contigous timestamps that should be binned together. Note that,
   in this case, for rows "left over" in the upper edge of the bin,
   their values are computed using timebin that would include rows
   with times earlier than them. For example, in an MS with 8 rows in
   one block to be processed and timebin=3, timestamps 1, 2, and 3
   would be used to compute the weights of the first three three
   rows, and rows 4, 5, and 6 would be used to compute weights for
   the next three rows as expected. Rows 7 and 8 are "left over"
   rows, but three rows (as per the integer timebin specification)
   are still used to compute them. Row 7 and 8 weights are computed
   by combining data in rows 6, 7, and 8.
   
   .. rubric:: Sliding Time Window Processing
   
   In the sliding time window case, in the case where timebin is a
   time quantity, the time window is always centered on the timestamp
   of the row in question and extends timebin 2 around that
   timestamp, subject the the time block boundaries. In the case
   where timebin is an integer, there are two cases to consider:
   
   #. timebin is odd: In this case the target row's data and the data
      from the +/-(n-1)/2 rows around the target row are also used.
   #. timebin is even: In this case, the target row's data and the
      data from the n/2 rows after the target row and the n/2 - 1
      rows before the target row are used.
   
   In all cases for "edge" rows, the timebin extends from the edge of
   the block to the corresponding timebin value of rows away from the
   edge, so that the timebin is not symmetrical around the target
   rows, but includes the number of rows specified by the timebin
   value.
   
   .. rubric:: Overriding Default Block Boundaries
   
   Rows with the same baselines and data description IDs which are
   included in that window are used for determining the weight of
   that row. The boundaries of the time block to which the window is
   restricted are determined by changes in FIELD_ID, ARRAY_ID, and
   SCAN_NUMBER. One can override this behavior for FIELD_ID and/or
   SCAN_NUMBER by specifying the combine parameter (see below).
   Unlike the time block processing algorithm, this sliding time
   window algorithm requires that details of all rows for the time
   window in question are kept in memory, and thus the sliding window
   algorithm in general and the block processing row when timebin is
   an int, requires more memory than the block processing method when
   timebin is a quantity. Also, unlike the block processing method
   which computes a single value for all weights within a single bin,
   the sliding window method requires that each row (along with each
   channel and correlation bin) be processed individually, so in
   general the sliding window method will take longer than the block
   processing method.

   
   .. rubric:: Channel Binning
   
   The width of channel bins is specified via the chanbin parameter.
   Channel binning occurs within individual spectral windows; bins
   never span multiple spectral windows. Each channel will be
   included in exactly one bin. The default value 'spw' indicates
   that all channels in each spectral window are to be included in a
   single bin.
   
   Any other string value is interpreted as a quantity, and so
   should have frequency units, e.g., "1MHz". In this case, the
   channel frequencies from the CHAN_FREQ column of the
   SPECTRAL_WINDOW subtable of the MS are used to determine the
   bins. The first bin starts at the channel frequency of the 0th
   channel in the spectral window. Channels with frequencies that
   differ by less than the value specified by the chanbin parameter
   are included in this bin. The next bin starts at the frequency
   of the first channel outside the first bin, and the process is
   repeated until all channels have been binned.

   If specified as an integer, the value is interpreted as the
   number of channels to include in each bin. The final bin in the
   spectral window may not necessarily contain this number of
   channels. For example, if a spectral window has 15 channels, and
   chanbin is specified to be 6, then channels 0-5 will comprise
   the first bin, channels 6-11 the second, and channels 12-14 the
   third, so that only three channels will comprise the final bin.
   
   .. rubric:: Minimum required number of visibilities
   
   The minsamp parameter allows the user to specify the minimum
   number of unflagged visibilities that must be present in a sample
   for that sample's weight to be computed. If a sample has less than
   this number of unflagged points, the associated weights of all the
   points in the sample are set to zero, and all the points in the
   sample are flagged.
   
   .. warning:: WARNING: Since statwt treats each baseline
      separately, selecting only a single channel in a spectral
      window will not satisfy the minimum number of samples (minsamp)
      if statwt is run with default parameters, leading to all the
      data in that spectral window being flagged. For such data, the
      user will need to change the default parameters in order to
      aggregate enough samples to satisfy minsamp (e.g., by setting
      combine='corr' if there are multiple correlation products, or
      timebin>1).

   
   .. rubric:: Aggregating data across boundaries
   
   By default, data are not aggregated across changes in values in
   the columns ARRAY_ID, SCAN_NUMBER, STATE_ID, FIELD_ID, and
   DATA_DESC_ID. One can override this behavior for SCAN_NUMBER,
   STATE_ID, and FIELD_ID by specifying the combine parameter. For
   example, specifying combine="scan" will ignore scan boundaries
   when aggregating data. Specifying combine="field, scan" will
   ignore both scan and field boundaries when aggregating data. Also
   by default, data for separate correlations are aggregated
   separately. Data for all correlations within each spectral window
   can be aggregated together by specifying "corr" in the combine
   parameter. Any combination and permutation of "scan", "field",
   "state", and "corr" are supported by the combine parameter. Other
   values will be silently ignored.

   
   .. rubric:: Statistics algorithms
   
   The supported statistics algorithms are described in detail in the
   imstat and ia.statistics() help. For the current application,
   these algorithms are used to compute vr and vi (see above), such
   that the set of the real parts of the visibilities and the set of
   the imaginary parts of the visibilities are treated as independent
   data sets.  Care should be taken not to tune these algorithms in a
   way that will discard significant portions of the tails of the
   underlying noise distribution (e.g., fence < 2 for the
   'HINGES-FENCES' algorithm).
