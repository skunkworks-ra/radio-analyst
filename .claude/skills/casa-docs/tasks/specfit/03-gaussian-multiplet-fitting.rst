   
   .. rubric:: Gaussian MULTIPLET FITTING
   
   Any number of Gaussian multiplets, each containing any number of
   two or more components, can be simultaneously fit, optionally with
   a polynomial and/or any number of Gaussian and/or Lorentzian
   singlets, the only caveat being that the number of parameters to
   be fit should be significantly less than the number of data
   points. The *gmncomps* parameter indicates the number of
   multiplets to fit and the number of components in each multiplet.
   In the case of a single multiplet, an integer (>1) can be
   specified. For example, *mgncomps=4* means fit a single quadruplet
   of Gaussians. In the case of 2 or more multiplets, an array of
   integers (all >1) must be specified. For example, *gmncomps=[2, 4,
   3]* means 3 separate multiples are to be fit, the zeroth being a
   doublet, the first being a quadruplet, and the second being a
   triplet.
   
   Initial estimates of all Gaussians in all multiplets are specified
   via gmampest, gmcenterest, and gmfwhmest (the so-called *gm*est*
   parameters) [b] parameters, which must be arrays of
   numbers. The input order starts with the zeroth component of the
   zeroth multiplet to the last component of the zeroth multiplet,
   then the zeroth component of the first multiplet to the last
   component of the first multiplet, etc to the zeroth component of
   the last multiplet to the last element of the last multiplet. The
   zeroth element of a multiplet is defined as the reference
   component of that multiplet and has the special significance that
   it is the profile to which all constraints of all other profiles
   in that multiplet are referenced (see below). So, in our example
   of *gmncomps=[2, 4, 3]* **,** *gmampest*, *gmcenterest*, and
   *gmfwhmest* must each be nine (the total number of individual
   Gaussian profiles summed over all multiplets) element arrays. The
   zeroth, second, and sixth elements represent parameters of the
   reference profiles in the zeroth, first, and second multiplet,
   respectively.
   
   The fixed relationships between the non-reference profile(s) and
   the reference profile of a multiplet are specified via the
   *gmampcon*, *gmcentercon*, and *gmfwhmcon* parameters. At least
   one, and any combination, of constraints can be specified for any
   non-reference component of a multiplet. The amplitude ratio of a
   non-reference line to that of the reference line is set in
   *gmampcon*. The ratio of the fwhm of a non-reference line to that
   of the reference line is set in *gmfwhmcon*. The offset in pixels
   of the center position of a non-reference line to that of the
   reference line is set in *gmcentercon*. In the case where a
   parameter is not constrained for any non-reference line of any
   multiplet, the value of the associated parameter must be 0. In the
   case of a single doublet, a constraint may be specified as a
   number or an array of a single number. For example, *mgncomps=2*
   and *gmampcon=0.65* and *gmcentercon=[32.4]* means there is a
   single doublet to fit where the amplitude ratio of the first to
   the zeroth line is constained to be 0.65 and the center of the
   first line is constrained to be offset by 32.4 pixels from the
   center of the zeroth line. In cases of a total of three or more
   Gaussians, the constraints parameters must be specified as arrays
   with lengths equal to the total number of Gaussians summed over
   all multiplets minus the number of reference lines (one per
   multiplet, or just number of multiplets, since reference lines
   cannot be constrained by themselves). In the cases where an array
   must be specified but a component in that array does not have that
   constraint, 0 should be specified. Here's an example:
   
   ::
   
      gmncomps=[2, 4, 3]
      gmampcon= [ 0 , 0.2, 0 , 0.1, 4.5, 0 ]
      gcentercon=[24.2, 45.6, 92.7, 0 , -22.8, -33.5]
      gfwhmcon=""
   
   In this case we have our previous example of one doublet, one
   quadruplet, and one triplet. The first component of the doublet
   has the constraint that its center is offset by 24.2 pixels from
   the zeroth (reference) component. The first component of the
   quadruplet is constrained to have an amplitude of 0.2 times that
   of the quadruplet's zeroth component and its center is constrained
   to be offset by 45.6 pixels from the reference component. The
   second component of the quadruplet is constained to have its
   center offset by 92.7 pixels from the associated reference
   component and the third component is constrained to have an
   amplitude of 0.1 times that of the associated reference component.
   The first component of the triplet is constrained to have an
   amplitude of 4.5 times that of its associated reference component
   and its center is constrained to be offset by -22.8 pixels from
   the reference component's center. The second component of the
   triplet is constrained to have its center offset by -33.5 pixels
   from the center of the reference component. No lines have FWHM
   constraints, so the empty string can be given for that parameter.
   Note that using 0 to indicate no constraint for line center means
   that one cannot specify a line centered at the same position as
   the reference component but having a different FWHM from the
   reference component. If you must specify this very unusual case,
   try using a very small positive (or even negative) value for the
   center constraint.
   
   Note that when a parameter for a line is constrained, the
   corresponding value for that component in the corresponding
   *gm*est* array is ignored and the value of the constrained
   parameter is automatically used instead. So let's say, for our
   example above, we had specified the following estimates:
   
   ::
   
      gmampest = [ 1, .2, 2, .1, .1, .5, 3, 2, 5]
      gmcenterest = [20, 10 , 30, 45.2, 609 , -233, 30, -859, 1]
   
   Before any fitting is done, the constraints would be taken into
   account and these arrays would be implicitly rewritten as:
   
   ::
   
      gmampest = [ 1, .2, 2, .4, .1, .2, 3, 13.5, 5 ]
      gmcenterest = [20, 44.2, 30, 75.6, 127.7, -233, 30, 7.2, -3.5]
   
   The value of *gmfwhmest* would be unchanged since there are no
   FWHM constraints in this example.
   
   In addition to be constrained by values of the reference
   component, parameters of individual components can be fixed. Fixed
   parameters are specified via the *gmfix* parameter. If no
   parameters are to be fixed, *gmfix* can be specified as the empty
   string or a zero element array. In the case where any parameter is
   to be fixed, *gmfix* must be specified as an array of strings with
   length equal to the total number of components summed over all
   multiplets. These strings encode which parameters to be fixed for
   the corresponding components. If a component is to have no
   parameters fixed, an empty string is used. In other cases one or
   more of any combination of parameters can be fixed using "p", "c",
   and/or "f" described above for fixing singlet parameters. There
   are a couple of special cases to be aware of. In the case where a
   non-reference component parameter is constrained and the
   corresponding reference component parameter is set as fixed, that
   parameter in the non-reference parameter will automatically be
   fixed even if it was specified not to be fixed in the *gmfix*
   array. This is the only way the constraint can be honored after
   all. In the converse case of when a constrained parameter of a
   non-reference component is specified as fixed, but the
   corresponding parameter in the reference component is not
   specified to be fixed, an error will occur. Fixing an
   unconstrained parameter in a non-reference component is always
   legal, as is fixing any combination of parameters in a reference
   component (with the above caveat that corresponding constrained
   parameters in non-reference components will be silently held fixed
   as well).
   
   The same rules that apply to singlets when *multifit=True* apply
   to multiplets.
