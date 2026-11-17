

.. _Examples:

Examples
   This example was taken from the Simulations `CASA Guide <https://casaguides.nrao.edu/index.php/Simulation_Guide_Component_Lists_(CASA_5.1)>`__ entitled 'Simulations Guide Component List'.

   ::

      default("simobserve")
      project = "FITS_list"
      skymodel = "Gaussian.fits"
      inwidth = "1GHz"
      complist = 'point.cl'
      compwidth = '1GHz'
      direction = "J2000 10h00m00.0s -30d00m00.0s"
      obsmode = "int"
      antennalist = 'alma.cycle9.1.cfg'
      totaltime = "28800s"
      mapsize = "10arcsec"
      thermalnoise = ''
      simobserve()

   This example demonstrates the use of the *comp_nchan* parameter to
   simulate a disk and produce a multi-channel MS (with a flat
   spectrum).

   ::

      simobserve(project="test_project",
                 complist="complist.cl",
                 compwidth="2000.00MHz",
                 comp_nchan=128,
                 integration="6.05s",
                 mapsize=['11.51arcsec'],
                 hourangle="1.5h",
                 totaltime="677.6s",
                 antennalist="antennalist.cfg",
                 sdantlist="aca.tp.cfg",
                 thermalnoise="")

   This example shows how to assign a central rest-frequency and channel width to a simulated image cube.

   ::

      simobserve(project=‘model_cube’,
                 skymodel=‘skymodel.image',
                 inwidth='0.4MHz',
                 antennalist='alma.cycle6.1.cfg',
                 direction="J2000 16h59m41.63s -40d03m43.61s",
                 obsmode="int", mapsize="2arcmin",
                 totaltime="1800s",
                 thermalnoise='',
                 incenter='86.6425GHz')

   This produces a data cube with a central rest-frequency of 86.6425 GHz and a channel width of 0.4 MHz. Note the Known Issue for simobserve that inwidth should not be specified in km/s.

.. _Development:

Development
   No additional development details

