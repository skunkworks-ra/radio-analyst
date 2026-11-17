   
   .. rubric:: Notes for *mode='add'*
   
   The behavior of *mode='add'* depends on the keyword that the user
   specifies under 'hdkey'. Below is a summary of the per keyword
   behavior of this mode. In general, the return value will be True
   if the operation succeeds, or False if it fails or is not
   supported. If unsuccessful or not supported, a message is normally
   logged which describes the failure. In most cases, you probably
   want to use *mode='put'* rather than *mode='add'*. We continue to
   support *mode='add'* mainly for backward compatibility.
   
   +--------------------------+------------------------------------------+
   | **Values**               | Description                              |
   +==========================+==========================================+
   | beammajor or bmaj        | If image has no beam(s), a single,       |
   |                          | global, circular beam of diameter        |
   |                          | specified in *hdvalue* is added.         |
   |                          | *hdvalue* must be a valid angular        |
   |                          | quantity (string or dictionary) or the   |
   |                          | operation will fail and False will be    |
   |                          | returned. If the image has a beam(s),    |
   |                          | the operation fails and False is         |
   |                          | returned. Examples of acceptable values  |
   |                          | of *hdvalue* are "4arcsec",              |
   |                          | **qa.quantity** ("4arcsec"), {'unit':    |
   |                          | 'arcsec', 'value': 4.0}. If you wish an  |
   |                          | image to have multiple beams, use        |
   |                          | **ia.setrestoringbeam** ().              |
   +--------------------------+------------------------------------------+
   | beamminor or bmin        | Behavior is the same as that for         |
   |                          | beammajor or bmaj.                       |
   +--------------------------+------------------------------------------+
   | beampa or bpa            | Operation has no effect and always       |
   |                          | returns False. If you wish to add a      |
   |                          | beam, use beammajor, bmaj, beamminor, or |
   |                          | bmin.                                    |
   +--------------------------+------------------------------------------+
   | bunit                    | If image has no brightness unit, add the |
   |                          | value specified in *hdvalue* which must  |
   |                          | be a unit supported by CASA. Else do     |
   |                          | nothing and return False.                |
   +--------------------------+------------------------------------------+
   | cdelt\*                  | No effect. Addition of coordinate system |
   |                          | parameters is not supported. Always      |
   |                          | returns False. Use the **cs** tool to    |
   |                          | add coordinates.                         |
   +--------------------------+------------------------------------------+
   | crpix\*                  | No effect. Addition of coordinate system |
   |                          | parameters is not supported. Always      |
   |                          | returns False. Use the **cs** tool to    |
   |                          | add coordinates.                         |
   +--------------------------+------------------------------------------+
   | crval\*                  | No effect. Addition of coordinate system |
   |                          | parameters is not supported. Always      |
   |                          | returns False. Use the **cs** tool to    |
   |                          | add coordinates.                         |
   +--------------------------+------------------------------------------+
   | ctype\*                  | No effect. Addition of coordinate system |
   |                          | parameters is not supported. Always      |
   |                          | returns False. Use the **cs** tool to    |
   |                          | add coordinates.                         |
   +--------------------------+------------------------------------------+
   | cunit\*                  | No effect. Addition of coordinate system |
   |                          | parameters is not supported. Always      |
   |                          | returns False. Use the **cs** tool to    |
   |                          | add coordinates.                         |
   +--------------------------+------------------------------------------+
   | datamax                  | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | datamin                  | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | date-obs or epoch        | No effect.                               |
   +--------------------------+------------------------------------------+
   | equinox                  | No effect.                               |
   +--------------------------+------------------------------------------+
   | imtype                   | If image type does not exist, add the    |
   |                          | type specified in *hdvalue*. *hdvalue*   |
   |                          | must be one of "Undefined", "Intensity", |
   |                          | "Beam", "Column Density",                |
   |                          | "Depolarization Ratio", "Kinetic         |
   |                          | Temperature", "Magnetic Field", "Optical |
   |                          | Depth", "Rotation Measure", "Rotational  |
   |                          | Temperature", "Spectral                  |
   |                          | Index","Velocity", or "Velocity          |
   |                          | Dispersion".                             |
   +--------------------------+------------------------------------------+
   | masks                    | No effect. Addition of masks is not      |
   |                          | supported. Use **ia.calcmask** ().       |
   +--------------------------+------------------------------------------+
   | maxpos                   | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | maxpixpos                | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | minpos                   | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | minpixpos                | No effect. Addition of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | object                   | If image has no object, add the value    |
   |                          | specified in *hdvalue*. Else do nothing  |
   |                          | and return False.                        |
   +--------------------------+------------------------------------------+
   | observer                 | If image has no observer, add the value  |
   |                          | specified in *hdvalue*. Else do nothing  |
   |                          | and return False.                        |
   +--------------------------+------------------------------------------+
   | projection               | No effect.                               |
   +--------------------------+------------------------------------------+
   | reffreqtype              | No effect.                               |
   +--------------------------+------------------------------------------+
   | restfreq                 | If image has a spectral coordinate and   |
   |                          | no rest frequency, set the rest          |
   |                          | frequency to the value specified in      |
   |                          | *hdvalue*. This value must be a valid    |
   |                          | CASA quantity with frequency units. Else |
   |                          | do nothing and return False. Examples of |
   |                          | valid values are "1GHz",                 |
   |                          | **qa.quantity** ("1GHz"), {'unit':       |
   |                          | 'GHz', 'value': 1.0}.                    |
   +--------------------------+------------------------------------------+
   | shape                    | No effect.                               |
   +--------------------------+------------------------------------------+
   | telescope                | If image has no telescope, add the value |
   |                          | specified in *hdvalue*. Else do nothing  |
   |                          | and return False.                        |
   +--------------------------+------------------------------------------+
   | any user defined keyword | Add the key-value pair if the key does   |
   |                          | not exist. Else do nothing and return    |
   |                          | False.                                   |
   +--------------------------+------------------------------------------+
