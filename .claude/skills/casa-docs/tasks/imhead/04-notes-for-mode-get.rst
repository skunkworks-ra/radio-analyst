
   
   .. rubric:: Notes for *mode='get'*
   
   The data type of the value returned by **imhead** when
   *mode='get'* depends on the keyword that the user specifies under
   'hdkey'. Below is a list of keywords on the data type that will be
   returned when *mode='get'* for each. A "quantity dictionary" is a
   dictionary with 'value' and 'unit' keys that can be used as input
   to various methods of the **qa** tool.
   
   +-------------------------+-------------------------------------------+
   | **Values**              |  **Description**                          |
   +-------------------------+-------------------------------------------+
   | beammajor or bmaj       | Returns quantity dictionary.              |
   +-------------------------+-------------------------------------------+
   | beamminor or bmin       | Returns quantity dictionary.              |
   +-------------------------+-------------------------------------------+
   | beampa or bpa           | Returns quantity dictionary.              |
   +-------------------------+-------------------------------------------+
   | bunit                   | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | cdelt\*                 | Returns quantity dictionary.              |
   +-------------------------+-------------------------------------------+
   | crpix\*                 | Returns float.                            |
   +-------------------------+-------------------------------------------+
   | crval\*                 | Returns quantity dictionary, unless the   |
   |                         | value for the stokes axis is requested,   |
   |                         | in which case an array of strings is      |
   |                         | returned.                                 |
   +-------------------------+-------------------------------------------+
   | ctype\*                 | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | cunit\*                 | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | datamax                 | Returns image pixel data type.            |
   +-------------------------+-------------------------------------------+
   | datamin                 | Returns image pixel data type.            |
   +-------------------------+-------------------------------------------+
   | date-obs or epoch       | Returns string (in YYYY/MM/DD/hh:mm:ss    |
   |                         | format).                                  |
   +-------------------------+-------------------------------------------+
   | equinox                 | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | imtype                  | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | masks                   | Returns string array.                     |
   +-------------------------+-------------------------------------------+
   | maxpos                  | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | maxpixpos               | Returns integer array.                    |
   +-------------------------+-------------------------------------------+
   | minpos                  | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | minpixpos               | Returns integer array.                    |
   +-------------------------+-------------------------------------------+
   | object                  | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | observer                | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | projection              | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | reffreqtype             | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | restfreq                | Returns quantity dictionary.              |
   +-------------------------+-------------------------------------------+
   | shape                   | Returns integer array.                    |
   +-------------------------+-------------------------------------------+
   | telescope               | Returns string.                           |
   +-------------------------+-------------------------------------------+
   | any user defined keword | Returns string.                           |
   +-------------------------+-------------------------------------------+
