   
   .. rubric:: Notes for *mode='del'*
   
   The behavior of *mode='del'* depends on the keyword that the user
   specifies under 'hdkey'. Below is a summary of the per keyword
   behavior of this mode. In general, the return value will be True
   if the operation succeeds, or False if it fails or is not
   supported. If unsuccessful or not supported, a warning message is
   normally logged which describes the failure.
   
   +--------------------------+------------------------------------------+
   | **Values**               |  **Description**                         |
   +--------------------------+------------------------------------------+
   | beammajor or bmaj        | Deletes all beams. Returns False if the  |
   |                          | image has no beams.                      |
   +--------------------------+------------------------------------------+
   | beamminor or bmin        | Deletes all beams. Returns False if the  |
   |                          | image has no beams.                      |
   +--------------------------+------------------------------------------+
   | beampa or bpa            | Deletes all beams. Returns False if the  |
   |                          | image has no beams.                      |
   +--------------------------+------------------------------------------+
   | bunit                    | Sets the associated value to the empty   |
   |                          | string.                                  |
   +--------------------------+------------------------------------------+
   | cdelt\*                  | No effect. Deletion of coordinate system |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | crpix\*                  | No effect. Deletion of coordinate system |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | crval\*                  | No effect. Deletion of coordinate system |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | ctype\*                  | No effect. Deletion of coordinate system |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | cunit\*                  | No effect. Deletion of coordinate system |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | datamax                  | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | datamin                  | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | date-obs or epoch        | No effect.                               |
   +--------------------------+------------------------------------------+
   | equinox                  | No effect.                               |
   +--------------------------+------------------------------------------+
   | imtype                   | No effect.                               |
   +--------------------------+------------------------------------------+
   | masks                    | Deletes the single mask specified in     |
   |                          | *hdvalue*, or if *hdvalue=''*, deletes   |
   |                          | all masks.                               |
   +--------------------------+------------------------------------------+
   | maxpos                   | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | maxpixpos                | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | minpos                   | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | minpixpos                | No effect. Deletion of statistical       |
   |                          | parameters is not supported.             |
   +--------------------------+------------------------------------------+
   | object                   | Sets the associated value to an empty    |
   |                          | string.                                  |
   +--------------------------+------------------------------------------+
   | observer                 | Sets the associated value to an empty    |
   |                          | string.                                  |
   +--------------------------+------------------------------------------+
   | projection               | No effect.                               |
   +--------------------------+------------------------------------------+
   | reffreqtype              | No effect.                               |
   +--------------------------+------------------------------------------+
   | restfreq                 | No effect.                               |
   +--------------------------+------------------------------------------+
   | shape                    | No effect.                               |
   +--------------------------+------------------------------------------+
   | telescope                | Sets the associated value to an empty    |
   |                          | string.                                  |
   +--------------------------+------------------------------------------+
   | any user defined keyword | Deletes the key-value pair.              |
   +--------------------------+------------------------------------------+
