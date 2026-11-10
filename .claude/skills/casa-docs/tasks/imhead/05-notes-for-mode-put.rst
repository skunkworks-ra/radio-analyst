
   
   .. rubric:: Notes for *mode='put'*
   
   In general, *mode='put'* will modify the specified key to the
   specified value that the user specifies under 'hdkey'. True is
   returned if the metadatum was successfully modified, False
   otherwise. Normally, a diagnostic message is logged if there is a
   failure. Only the parameter specified is modified; e.g., no
   modification of reference direction occurs to implicitly account
   for precession to a new reference frame. The following are the
   exceptional cases for *mode='put'*.
   
   +--------------------------+------------------------------------------+
   | **Values**               |  **Description**                         |
   +--------------------------+------------------------------------------+
   | beammajor or bmaj        | Will always fail if image has multiple   |
   |                          | beams. Use **ia.setrestoringbeam** ()    |
   |                          | in this case. If image has no beam(s), a |
   |                          | single, global, circular beam of         |
   |                          | diameter specified in *hdvalue* is       |
   |                          | added. *hdvalue* must be a valid angular |
   |                          | quantity (string or dictionary) or the   |
   |                          | operation will fail and False will be    |
   |                          | returned. If the image has a single      |
   |                          | beam, the value of the major axis will   |
   |                          | be modified, unless the specified value  |
   |                          | is smaller than the minor axis of the    |
   |                          | existing beam, in which case nothing is  |
   |                          | modified and False is returned. Examples |
   |                          | of acceptable values of *hdvalue* are    |
   |                          | "4arcsec", **qa.quantity** ("4arcsec"),  |
   |                          | {'unit': 'arcsec', 'value': 4.0}.        |
   +--------------------------+------------------------------------------+
   | beamminor or bmin        | Behavior is the same as that for bmaj,   |
   |                          | although of course if the image already  |
   |                          | has a single beam, the specified value   |
   |                          | must be less than the existing major     |
   |                          | axis value, or nothing is modified and   |
   |                          | False is returned.                       |
   +--------------------------+------------------------------------------+
   | beampa or bpa            | If the image does not already have a     |
   |                          | single beam, nothing is modified and     |
   |                          | False is returned. Angular units are     |
   |                          | required.                                |
   +--------------------------+------------------------------------------+
   | bunit                    | Fails if *hdvalue* is not a supported    |
   |                          | CASA unit.                               |
   +--------------------------+------------------------------------------+
   | cdelt *n*                | One-based axis *n* must be less than or  |
   |                          | equal to the number of axes in the       |
   |                          | image. *hdvalue* type must be a number   |
   |                          | (in which case the unit of the           |
   |                          | corresponding axis is assumed) or a      |
   |                          | quantity (string or dictionary). If a    |
   |                          | quantity, the unit must conform to the   |
   |                          | existing axis unit.                      |
   +--------------------------+------------------------------------------+
   | crpix *n*                | One-based axis *n* must be less than or  |
   |                          | equal to the number of axes in the       |
   |                          | image. *hdvalue* type must be a number.  |
   |                          | Will fail if the polarization axis is    |
   |                          | specified.                               |
   +--------------------------+------------------------------------------+
   | crval *n*                | One-based axis *n* must be less than or  |
   |                          | equal to the number of axes in the       |
   |                          | image. If not the polarization/stokes    |
   |                          | axis, *hdvalue* type must be a number    |
   |                          | (in which case the unit of the           |
   |                          | corresponding axis is assumed), a        |
   |                          | quantity (string or dictionary), or a    |
   |                          | valid measurement format (such as a      |
   |                          | sexagesimal direction axis specification |
   |                          | for an axis with angular units). If a    |
   |                          | quantity, the unit must conform to the   |
   |                          | existing axis unit. If the               |
   |                          | stokes/polarization axis, one must       |
   |                          | provide an array of stokes/polarization  |
   |                          | strings (e.g., ["I", "Q", "XX"]) that is |
   |                          | the same length as the stokes axis. If   |
   |                          | the stokes axis is degenerate, one can   |
   |                          | alternatively provide a string           |
   |                          | indicating the stokes value (e.g. "U").  |
   +--------------------------+------------------------------------------+
   | ctype *n*                | One-based axis *n* must be less than or  |
   |                          | equal to the number of axes in the       |
   |                          | image. *hdvalue* type must be a string.  |
   +--------------------------+------------------------------------------+
   | cunit *n*                | One-based axis *n* must be less than or  |
   |                          | equal to the number of axes in the       |
   |                          | image. Specified unit must conform to    |
   |                          | the existing axis unit. Will fail if     |
   |                          | stokes/polarization axis is specified.   |
   +--------------------------+------------------------------------------+
   | datamax                  | This cannot be modified. False is always |
   |                          | returned.                                |
   +--------------------------+------------------------------------------+
   | datamin                  | This cannot be modified. False is always |
   |                          | returned.                                |
   +--------------------------+------------------------------------------+
   | date-obs or epoch        | A valid time specification must be       |
   |                          | given.                                   |
   +--------------------------+------------------------------------------+
   | equinox                  | A valid direction reference frame        |
   |                          | specification string must be given.      |
   +--------------------------+------------------------------------------+
   | imtype                   | A CASA-supported image type string must  |
   |                          | be given or the image type will be set   |
   |                          | to 'Intensity'.                          |
   +--------------------------+------------------------------------------+
   | masks                    | Masks may not be modified. False is      |
   |                          | always returned.                         |
   +--------------------------+------------------------------------------+
   | maxpos                   | This cannot be modified.                 |
   +--------------------------+------------------------------------------+
   | maxpixpos                | This cannot be modified.                 |
   +--------------------------+------------------------------------------+
   | minpos                   | This cannot be modified.                 |
   +--------------------------+------------------------------------------+
   | minpixpos                | This cannot be modified.                 |
   +--------------------------+------------------------------------------+
   | object                   | *hdvalue* must be a string.              |
   +--------------------------+------------------------------------------+
   | projection               | *hdvalue* must be a string representing  |
   |                          | a supported CASA projection              |
   |                          | specification.                           |
   +--------------------------+------------------------------------------+
   | reffreqtype              | *hdvalue* must be a string representing  |
   |                          | a supported CASA velocity reference      |
   |                          | frame specification.                     |
   +--------------------------+------------------------------------------+
   | restfreq                 | *hdvalue* can be a number (in which case |
   |                          | frequency axis units are assumed) or a   |
   |                          | valid quantity string or quantity        |
   |                          | dictionary in which case the unit must   |
   |                          | conform to Hz. Only the active rest      |
   |                          | frequency may be modified. The spectral  |
   |                          | coordinate can hold several rest         |
   |                          | frequencies (e.g., to handle an          |
   |                          | observations where the band covers many  |
   |                          | lines), but only one is active (for      |
   |                          | velocity conversion) at any time. For    |
   |                          | more functionality, please use           |
   |                          | **cs.setrestfrequency** ().              |
   +--------------------------+------------------------------------------+
   | shape                    | This cannot be modified.                 |
   +--------------------------+------------------------------------------+
   | telescope                | *hdvalue* must be a string.              |
   +--------------------------+------------------------------------------+
   | any user defined keyword | *hdvalue* can be practically any         |
   |                          | supported input parameter type.          |
   +--------------------------+------------------------------------------+
