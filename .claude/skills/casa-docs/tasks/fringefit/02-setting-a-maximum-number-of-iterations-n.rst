   
   .. rubric:: Setting a maximum number of iterations: *niter*
   
   A maximum number of iterations for the global least squares solver
   can be set with the *niter* parameter. The default is 100; in
   cases with high signal-to-noise this limit is not reached.
   
   .. rubric:: Constrain the search window for delay: *delaywindow*
   
   Sometimes a priori information is available to constrain the
   delays relative to the reference station at the FFT search step.
   The upper and lower bounds (in nanoseconds) can be provided as a
   two element list through the keyword *delaywindow*. The value None
   can be used to leave either the upper or lower limit unconstrained
   (setting both to None constrains neither; this is the default).
   Note that the same constraint is applied to all baselines in the
   FFT search step.
   
   .. rubric:: Constrain the search window for rate: *ratewindow*
   
   Similarly to *delaywindow*, sometimes a priori information is
   available to constrain the delay rates relative to the reference
   station at the FFT search step. The upper and lower bounds (in
   units of seconds/second) can be provided as a two element list
   through the keyword *ratewindow*. The value None can be used to
   leave either the upper or lower limit unconstrained (setting both
   to None constrains neither; this is the default). Note that the
   same constraint is applied to all baselines in the FFT search
   step.
   
   .. rubric:: Spectral window combination modes: *concatspws*

   For *combine='spw'*, the multi-band FFT solution can be done in two 
   different ways. For *concatspws=True* (the default, and the 
   traditional behavior), spws are combined onto a wider frequency 
   grid. This may not be optimal for spws that do not naturally fall 
   on the same global frequency grid, or which vary in their channel widths. 
   In a new experimental mode, *concatspws=False*, each spw is separately 
   FFT'd, and the results are combined using the shift theorem. This 
   enables support for more flexibility in the variety of spws to be 
   combined. This mode remains experimental because some fine-tuning 
   of the net delay resolution in the spw aggregation is under further 
   study. In either case, it is important to ensure the nominal 
   coherence of the spectral windows by applying a 'manual phase cal' 
   solution from a strong source scan; electronic stability among spws 
   is also required.
   
   .. rubric:: Select active parameters for least square solver: *paramactive*
   
   As part of the inclusion of a dispersive component of delay we
   have added a parameter to control which model parameters are used
   in the least-squares part of the solver (the FFT stage is
   unaffected). The *paramactive* parameter takes a Python list of
   boolean arguments for the delay, rate and dispersive components,
   with a default value of [True, True, False] to match the historic
   default, which is also expected to be the most common future
   use-case. Note that we do not offer users an opportunity not to
   solve for phase offset (also known as "secular phase").

   .. rubric:: Control correlation-dependent flagging: *corrdepflags*

   Traditionally, CASA adopts a conservative approach to interpreting
   correlation-dependent flags, wherein all correlations in a single 
   visibility vector are assumed flagged if any one of them is 
   (*corrdepflags=False*).  In some cases, it is desirable to relax 
   this stricture, by setting *corrdepflags=True*.   This is necessary, 
   for example, to prevent single-polarization antennas in VLBI arrays
   from being completely flagged when observing with dual-polarization
   antennas.   

   .. rubric:: Control correlation combination for solving:  *corrcomb*

   When the parallel-hand correlations have been made coherent (e.g., by 
   "manual phase-cal" on a strong calibrator), sensitivity can be improved
   on weak sources by combining the parallel-hand correlations for 
   *fringefit* solving.  This can be achieved in two modes:

   - *corrcomb='stokes'* => combine the parallel hand correlations to formally
     form Stokes I visibilities, respecting the (possibly different) relative 
     per-correlation weights and properly propagating then to the result.  
     This ensures that any source polarization contribution to the parallel hands 
     is formally cancelled.  When the weights are not equal, the net sensitivity 
     gain will be less than sqrt(2).  In the limit that one correlation is flagged 
     (i.e., its weight it effectively zero), Stokes I cannot formally be formed, 
     and the visibility will be flagged.

   - *corrcomb='parallel'* => combine the parallel-hand correlations in a simple
     weighted average.   This will optimize the combined sensitivity (as much as sqrt(2)
     improvement when the weights are equal), but assumes that there is no source 
     polarization contribution to either correlation that will fail to cancel in the 
     combination.   It is usually desirable to use *corrdepflags=True* when using
     *corrcomb='parallel'*, to avoid excessive flagging of solutions.  This is critical
     when fringe-fitting VLBI arrays which include a subset of single-polarization
     antennas.

   The default, *corrcomb='none'*, means that the parallel-hand correlations will not
   be combined for *fringefit* solving, and per-polarization solutions will be obtained.
