   
   .. rubric:: Tracking moving sources or sources with ephemeris tables
   
   If the phasecenter is a known major solar system object
   ('MERCURY', 'VENUS', 'MARS', 'JUPITER', 'SATURN', 'URANUS',
   'NEPTUNE', 'PLUTO', 'SUN', 'MOON') or is an ephemerides table,
   then that source is tracked and the background sources get smeared
   (which is useful especially for long observations or multi epoch
   data). The ephemeris table can be either the one attached to the MS 
   in FIELD table or an externally provided one such as one generated 
   by getephemtable. The table name should include a proper (relative/absolute) 
   path in order to tclean to find the correct one.  
   There is a special case, when phasecenter='TRACKFIELD' (it should
   be in all caps),
   which will use the ephemerides or polynomial phasecenter in the
   FIELD table of the MeasurementSets as the source center to track.
   When in tracking mode,  the image center will be the direction of
   the source at the first time in the user selected data. At all
   other times, the source will be shifted by the amount it has moved
   in the frame of the image to that initial time. Examples of usage
   are presented in the **tclean** examples tab.
   
   .. note:: When displaying ephemeris images, it is good practice
      to use relative coordinates to determine the average offset of
      emission from the ephemeris path over the observation, i.e.,
      axis label properties: world coordinate, relative position. The
      use of the absolute grid (default) can be misleading since the
      chosen coordinate frame is associated with the ephemeris path
      location at an unspecified time, although usually near the
      beginning of the experimient.
   
   More information can be found in the CASA Docs chapter on
   Ephemeris Data.


   .. rubric:: Multiple MSs

   For the input visivility data, tclean can accept multiple MSs. The 
   details on conformance checks that are performed on the list of MSs 
   are summarized in the CASA Docs page on Combining Datasets.

   .. rubric:: History

   At the end of a successful tclean run, the history of the output
   images is updated. For every tclean command a series of entries is
   recorded, including the task name (tclean), the CASA version used,
   and every parameter-value pair of the task.

   The history is written to all the images associated with the
   current run, identified by the image base name given in the
   imagename parameter. This feature searches for all the images with
   names starting with that basename and followed by a dot-separated
   extension (imagename.\*). In addition it also searches for
   imagename[INTEGERS]_[INTEGERS].\*, to cover auto-incremented image
   names (see the table of possible image names above).

   The image history entries added by tclean can be inspected using
   the task imhistory (`see tasks API`_), similarly as
   with the history entries added by other image analysis tasks.

   As a lower level interface, the image history can be also inspected
   and manipulated using CASA tools such as the image analysis tool
   and the table tool (`see tools API`_). The history
   entries are written into the 'logtable' subtable of the images.

   .. note:: Because history is written into all the images found with
             the 'imagename' prefix and a dot-separated extension,
             there is a corner case where history entries can be
             written in images that are not related to the tclean
             command just executed. For example, if a first tclean
             command used imagename='tst.mfs.hogbom', and a second
             command uses imagename='tst.mfs'. This can happen if the
             tclean commands use the same directory, the imagename
             string is a shorter version of a previously used
             imagename, and the longer name is used first and is the
             shorter name (to be used afterwards) followed by a dot
             '.' and more characters. This naming scheme produces an
             ambiguity with the rules used to name output images
             (imagename + '.' + multiple extensions) and is risky, as
             it can be very difficult for the user to anticipate all
             the possible conflicts and confusions with image
             extensions used by tclean and other imaging tasks.

   .. rubric:: Processing information

   Several parameters related to runtime processing are added to the
   miscinfo (miscellaneous information) record of the images produced
   by tclean. These are technical parameters related to processes and
   memory use:

   - mpiprocs: integer, number of processes (>1 for parallel runs)
   - chnchnks: integer, number of sub-cubes or chanchunks into which
     cubes are partitioned in the major cycles
   - memavail: float, estimated available memory, as found by tclean
     at the beginning of the first major cycle.
   - memreq: float, estimate of memory required, as a function of cube
     size, number of processors, and a few heuristic scale
     factors. Expressed in GBs.

   These parameters are added to the miscinfo record of the output
   images by the tclean command that creates them, and represent the
   runtime processing information of that command.

   Similarly as with other parameters included in the miscinfo record,
   these are exported to FITS images by the exportfits task, if the
   parameter history is True.  The miscinfo record can be inspected
   using the image tool (`see tools API`_).

   The same values are written to the CASA log at the beginning of
   every major cycle. The `memreq` estimate should not be interpreted
   as the amount of memory that tclean is going to use. It is an
   estimate of memory that would be required to fit all the data in
   memory, also accounting for the fact that that multiple processes
   would work on the data simultaneously if running in parallel
   mode.

   The `memreq` value is used to estimate the required `chnchnks` or
   number of sub-cubes into which the data are partitioned in the
   major cycles. `chnchnks` is roughly estimated as the result from
   dividing `memreq` by `memavail`. The amount of memory effectively
   used is kept below the estimated amount of memory available, thanks
   to the partitioning of the data in sub-cubes and further finer
   partitioning done in the minor cycles. The `memreq` estimate grows
   proportionally to the data dimensions, type of gridder, and number
   of processes in parallel mode.

   .. _see tasks API: ../casatasks.rst
   .. _see tools API: ../casatools.rst
