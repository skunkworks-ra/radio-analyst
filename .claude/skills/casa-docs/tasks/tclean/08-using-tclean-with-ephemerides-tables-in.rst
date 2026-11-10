
   
   .. rubric:: Using tclean with ephemerides tables in CASA format

   When you have an ephemeris table called, des_deedee_ephem.tab that covers the whole observations
   
   ::
   
      tclean(vis=['MS1.ms', 'MS2.ms', 'MS3.ms', 'MS4.ms', 'MS5.ms'],
             selectdata=True, field="DES_DEEDEE",
             spw=['17,19,21,23','17,19,21,23','17,19,21,23','17,19,21,23','17,19,21,23'],
             intent="OBSERVE_TARGET#ON_SOURCE", datacolumn="data",
             imagename="test_track", imsize=[2000, 2000], cell=['0.037arcsec'],
             phasecenter="des_deedee_ephem.tab", stokes="I")
   
   You can check whether the ephermeris table is of the format
   that CASA accepts by using the measures tool me.framecomet
   function:

   ::
   
      me.framecomet('des_deedee_ephem.tab')
   
   If this tool accepts the input without complaint, then the same
   should work in tclean.
   If the source you are tracking is one of the ten sources for
   which the CASA measures tool has the ephemerides from the JPL
   DE200 or DE405, then you can use their names directly:

   ::
   
      tclean(vis=['uid___A002_Xbc74ea_X175c.ms',
                  'uid___A002_Xbc74ea_X1af4.ms',
                  'uid___A002_Xbc74ea_X1e19.ms',
                  'uid___A002_Xbc74ea_X20b7.ms'],
             selectdata=True, field="Jupiter",
             spw=['17,19,21,23','17,19,21,23','17,19,21,23','17,19,21,23'],
             intent="OBSERVE_TARGET#ON_SOURCE", datacolumn="corrected",
             imagename="alltogether", imsize=[700, 700], cell=['0.16arcsec'],
             phasecenter="JUPITER", stokes="I")
   
   For ALMA data mainly the correlator may have the ephemerides of
   a moving source already attached to the FIELD tables of the
   MeasurementSets (as it was used to phase track the source). In
   such special cases, you can use the keyword "TRACKFIELD" in the
   phasecenter parameter, and then the internal ephemerides will
   be used to track the source.
   
   ::
   
      tclean(vis=['MS1.ms', 'MS2.ms', 'MS3.ms', 'MS4.ms', 'MS5.ms'],
             selectdata=True, field="DES_DEEDEE",
             spw=['17,19,21,23','17,19,21,23','17,19,21,23','17,19,21,23','17,19,21,23'],
             intent="OBSERVE_TARGET#ON_SOURCE", datacolumn="data",
             imagename="test_track", imsize=[2000, 2000],
             cell=['0.037arcsec'], phasecenter="TRACKFIELD", stokes="I")

.. _Development:

Development
   In future releases of CASA6, the tclean task will include an option for MFS and
   MTMFS deconvolution along with cube major cycles, and GPU gridding options for
   the VLASS observing program. 
