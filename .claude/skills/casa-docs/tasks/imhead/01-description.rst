

.. _Returns:

Returns
   out (dict) - keyword value, when mode='get'. Image metainformation
   when mode='summary'. Supported keywords when mode='list'


.. _Description:

Description
   imhead task: List, get and put image header parameters.
   
   This task allows the user to manipulate metadata associated with a
   CASA image. Both float and complex valued images are fully
   supported.
   
   .. note:: NOTE: For measurement sets, the task vishead should be used.
   
    The supported mode values are:
   
   +---------+-----------------------------------------------------------+
   | Values  |  **Description**                                          |
   +---------+-----------------------------------------------------------+
   | add     | Add a new metadata value to the image.                    |
   +---------+-----------------------------------------------------------+
   | del     | Delete a key or reset its value to a fiducial value if    |
   |         | possible. Ignores *hdvalue* parameter.                    |
   +---------+-----------------------------------------------------------+
   | get     | Return the specified keyword value. Ignores the *hdvalue* |
   |         | parameter.                                                |
   +---------+-----------------------------------------------------------+
   | history | Log image history. Ignores the *hdkey* and *hdvalue*      |
   |         | parameters.                                               |
   +---------+-----------------------------------------------------------+
   | list    | Show supported keywords and their values. Ignores the     |
   |         | *hdkey* and *hdvalue* parameters.                         |
   +---------+-----------------------------------------------------------+
   | put     | Modify the value associated with the keyword using the    |
   |         | specified value.                                          |
   +---------+-----------------------------------------------------------+
   | summary | Log a summary of the image and return a dictionary of     |
   |         | various metadata values. Ignores the *hdkey* and          |
   |         | *hdvalue* parameters.                                     |
   +---------+-----------------------------------------------------------+
   
   See below for details about how these modes act for specific
   keywords.
   
   .. warning:: ALERT: Only limited checking is implemented to ensure modifying
      a specific value will leave the image metadata in a consistent
      state, so, if one is not careful, one could end up with an
      image that has an inconsistent set of metadata and is
      therefore, nonsensical and useless.
   
      That is, PROCEED AT YOUR OWN RISK when using modes add, del, or
      put.
   
   .. rubric:: Notes for *mode='list'*
   
   Supported keywords that can be listed with parameter 'hdkey' when
   using mode='list':
   
   +-------------------+-------------------------------------------------+
   | **Values**        | Description                                     |
   +===================+=================================================+
   | beammajor or bmaj | Major axis of the clean beam.                   |
   +-------------------+-------------------------------------------------+
   | beamminor or bmin | Minor axis of the clean beam.                   |
   +-------------------+-------------------------------------------------+
   | beampa or bpa     | Position angle of the clean beam. **NOTE**: If  |
   |                   | the image contains multiple beams, use          |
   |                   | *mode='summary'* to list them with              |
   |                   | *verbose=True*.                                 |
   +-------------------+-------------------------------------------------+
   | bunit             | Image units (K, Jy/beam, etc).                  |
   +-------------------+-------------------------------------------------+
   | cdelt *n*         | Pixel size, *n* th axis. *n* is one-based.      |
   +-------------------+-------------------------------------------------+
   | crpix *n*         | The pixel designated as the reference location, |
   |                   | *n* th axis *n* is one-based.                   |
   +-------------------+-------------------------------------------------+
   | crval *n*         | World coordinate value of the reference pixel   |
   |                   | for the *n* th axis. *n* is one-based.          |
   +-------------------+-------------------------------------------------+
   | ctype *n*         | Name of *n* th axis. *n* is one-based.          |
   +-------------------+-------------------------------------------------+
   | cunit *n*         | Units of *n* th axis. *n* is one based.         |
   +-------------------+-------------------------------------------------+
   | datamax           | Maximum pixel value.                            |
   +-------------------+-------------------------------------------------+
   | datamin           | Minimum pixel value.                            |
   +-------------------+-------------------------------------------------+
   | date-obs          | Date (epoch) of the observation.                |
   +-------------------+-------------------------------------------------+
   | equinox           | Direction reference frame.                      |
   +-------------------+-------------------------------------------------+
   | imtype            | Image type (e.g. Intensity).                    |
   +-------------------+-------------------------------------------------+
   | minpos            | World coordinate position of minimum pixel      |
   |                   | value.                                          |
   +-------------------+-------------------------------------------------+
   | minpixpos         | Pixel coordinate position of minimum pixel      |
   |                   | value.                                          |
   +-------------------+-------------------------------------------------+
   | maxpos            | World coordinate position of maximum pixel      |
   |                   | value.                                          |
   +-------------------+-------------------------------------------------+
   | maxpixpos         | Pixel coordinate position of maximum pixel      |
   |                   | value.                                          |
   +-------------------+-------------------------------------------------+
   | object            | Source name.                                    |
   +-------------------+-------------------------------------------------+
   | observer          | Observer name.                                  |
   +-------------------+-------------------------------------------------+
   | projection        | Direction coordinate projection (e.g.           |
   |                   | 'SIN','TAN', or 'ZEA').                         |
   +-------------------+-------------------------------------------------+
   | reffreqtype       | Spectral reference frame.                       |
   +-------------------+-------------------------------------------------+
   | restfreq          | Rest Frequency.                                 |
   +-------------------+-------------------------------------------------+
   | shape             | Number of pixels along each axis.               |
   +-------------------+-------------------------------------------------+
   | telescope         | Telescope name.                                 |
   +-------------------+-------------------------------------------------+
