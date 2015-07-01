#!/usr/bin/env python
"""
.. module:: pymeteo.skewt
   :platform: Unix, Windows
   :synopsis: Skew-T/Log-P plotting

.. moduleauthor:: Casey Webster <casey.webster@gmail.com>

This module allows plotting Skew-T/Log-P diagrams 
and hodographs from arrays of 
data with helper functions to plot directly from CM1 output files
in either Grads or HDF5 format and also from sounding data text
files in the format used for WRF and CM1 initialization.

This module also has code to produce rudimentary analysis of
the soundings data.  Currently this is limited to CAPE (surface 
and most unstable), CIN, wind shear, storm relative helicity, lifted index
and a rough estimate of storm motion based on the Bunkers (2000)
method.

.. figure:: _static/images/skewt.png
  :align: center

  Example Skew-T/Log-P with hodograph

Plotting
++++++++

High level plotting functions
-----------------------------

* :py:func:`plot_cm1h5` -- plots skewt from CM1 generated hdf5 files processed by ingest_cm1
* :py:func:`plot_cm1` -- plots skewt from CM1 generated GRaDS style output
* :py:func:`plot_sounding_data` -- plots skewt from CM1/WRF input sounding files
* :py:func:`plot` -- generic high level plot function

Variables affecting the plot output
-----------------------------------

These variables affect the skewness of the plot and the bounds of the plot

* :py:data:`skew_angle` -- skewness
* :py:data:`Tmin`, :py:data:`Tmax` -- T dimension bounds (temperature, C)
* :py:data:`pbot`, :py:data:`ptop` -- p dimension bounds (pressure, Pa)

Functions to draw isolines
--------------------------

If you are manually plotting skew-t data, these functions can be used to draw
various lines on your plot.  These are used by the high level plotting functions.

* :py:func:`draw_isotherms`
* :py:func:`draw_isobars`
* :py:func:`draw_dry_adiabat`
* :py:func:`draw_moist_adiabat`
* :py:func:`draw_water_mix_ratio`

Module reference
++++++++++++++++

"""
import math
import pymeteo.thermo as met
import pymeteo.dynamics as dyn
import numpy as np
import matplotlib.pyplot as plt
import h5py
import pymeteo.cm1.read_grads as cm1
import pymeteo.interp

# This defines the skew-angle of the T axis
skew_angle = 37.5 
"""This defines the skewness of the T axis"""

# These define the domain plotted.  T values are at @1000 mb (e.g. unskewed)
Tmin = -40.0
"""Sets the left boundary of the plot. Temperature at 1000 mb (C)"""
Tmax = 40.0
"""Sets the right boundary of the plot. Temperature at 1000 mb (C)"""
pbot = 105000.0
"""Sets the bottom boundary of the plot. Pressure (Pa)"""
ptop = 10000.0
"""Sets the top boundary of the plot. Pressure (Pa)"""

## Values below used for plotting 
dp = 5000.0
"""The delta pressure used in calculating adiabats"""
ptickbot = 100000.0
"""Lowest elevated pressure level to be labelled in the plot (Pa)"""
pticktop = 10000.0
"""Highest elevated pressure level to be labelled in the plot (Pa)"""
tickdp = 10**4
"""The spacing between pressure labels in the plot (Pa)"""
plevs = np.arange(pbot,ptop-1,-dp)
"""List of pressure levels to do calculations on"""
fontscalefactor = 1

#for plotted lines
pb_plot=105000
pt_plot=10000
pt_plot2=20000
dp_plot=1000
plevs_plot = np.arange(pb_plot,pt_plot-1,-dp_plot)
plevs_plot2 = np.arange(pb_plot,pt_plot2-1,-dp_plot)
plevs_std = [100000,85000,70000,50000,40000,30000,25000,20000,15000]

#TODO: enforce square w/ aspect ratio of plot
#Domain of the hodograph
umin = -22.5
umax = 27.5
vmin = -12.5
vmax = 27.5

##################################################################################
def plot_cm1h5(filename, xi, yi, output):
    """ Plots a skewt from an HDF5 file.

    :param filename: The name of the HDF5 file to open.
    :type filename: str
    :param xi: The X gridpoint of the skewt plot.
    :type xi: int
    :param yi: The Y gridpoint of the skewt plot.
    :type yi: int
    :param output: Output filename to save plot
    :type output: str

    To use this function the HDF5 file must have the following
    variables:

    - *xh* -- x scalar grid locations
    - *yh* -- y scalar grid locations
    - *z* -- z grid locations
    - *time* -- timestep of file data (scalar)
    - *th* -- potential temperature (K)
    - *thpert* -- potential temperature perturbation (K)
    - *prs* -- pressure (Pa)
    - *u* -- u wind speed (m/s)
    - *v* -- v wind speed (m/s)
    - *qv* -- water vapor mixing ratio (kg/kg)

    The names of these variables correspond to default naming by 
    CM1 using HDF5 output.

    """
    f = h5py.File(filename, 'r')
    z = f["/mesh/zh"][:]    # m 

    x = f["/mesh/xh"][xi]   # m
    y = f["/mesh/yh"][yi]   # m
    t = f["/time"][0]       # s
    th = f["/3d_s/thpert"][:,yi,xi] + f["/basestate/th0"][:] # K
    p = f["/3d_s/ppert"][:,yi,xi] + f["/basestate/pres0"][:] # Pa
    u = f["/3d_u/u"][:,yi,xi] # m/s
    v = f["/3d_v/v"][:,yi,xi] # m/s
    qv = f["/3d_s/qvpert"][:,yi,xi] 

    print(x,y,z[0],t,th[0],u[0],v[0],p[0],qv[0])
    plot(x,y,z,t,th,p,qv,u,v,filename, output)

##################################################################################
#
def plot_sounding_data(filename, output):
        """Plot SkewT from a WRF / CM! compatible sounding data file
    
        :param filename: The name of the file to open.
        :type filename: str
        :param output: The name of the file to output plot
        :type output: str

        The datafile is the same format as used in sounding initalization
        files for WRF and CM1. This format contains tabular data with
        the following fields:

        - pressure (mb)
        - height (m)
        - temperature (C)
        - dew point (C)
        - wind direction (degrees)
        - wind speed (m/s)
        
        Missing values should be filled with the value -9999.00
        """

        p,z,T,Td,wdir,wspd = np.loadtxt(filename, delimiter=',',  unpack=True)
        # Pressure to Pa
        p = p * 100.

        # z to km
        #z = z / 1000.
        
        # interpolate missing wind

        nk = len(z)
        u = np.empty(nk, np.float32)
        v = np.empty(nk, np.float32)

        for k in range(nk):
           if wdir[k] == -9999. and wspd[k] == -9999.:
              u[k] = v[k] = -9999.
           else:
              u[k], v[k] = dyn.wind_deg_to_uv(wdir[k], wspd[k])

           #print('{0:5.2f} {1:5.2f} = {2:5.2f} {3:5.2f}'.format(wdir[k], wspd[k], u[k], v[k]))
           
        _z = np.empty(2,np.float32)
        _u = np.empty(2,np.float32)
        _v = np.empty(2,np.float32)
        print('INTERPOLATING')
        for k in range(nk):
           if wdir[k] == -9999. and wspd[k] == -9999.:
              kb = ke = k
              while kb >= 0 and wdir[kb] == -9999. and wspd[kb] == -9999.:
                 kb -= 1
              while ke <= nk-1 and wdir[ke] == -9999. and wspd[ke] == -9999.:
                 ke += 1

              # everything in bounds
              if kb >= 0 and ke <= nk-1:
                 _z[0] = z[kb]
                 _z[1] = z[ke]
                 _u[0] = u[kb]
                 _u[1] = u[ke]
                 _v[0] = v[kb]
                 _v[1] = v[ke]
                 
                 u[k] = pymeteo.interp.linear(_z, _u, z[k])
                 v[k] = pymeteo.interp.linear(_z, _v, z[k])

              elif kb < 0:
                 u[k] = u[ke]
                 v[k] = v[ke] 
              elif ke > nk-1:
                 u[k] = u[kb]
                 v[k] = v[kb] 

        for k in range(nk):
           # kt to m/s
           u[k] = u[k] * 0.5144444
           v[k] = v[k] * 0.5144444
        #   print('{0:5.2f} {1:5.2f} = {2:5.2f} {3:5.2f}'.format(wdir[k], wspd[k], u[k], v[k]))

        # calc theta
        th = np.empty(nk, np.float32)
        # calc qv
        qv = np.empty(nk, np.float32)
        for k in range(nk):
           th[k] = met.theta(T[k]+met.T00, p[k]) 
           w = met.es(Td[k]+met.T00) / met.es(T[k]+met.T00)
           pp = met.es(T[k]+met.T00) / p[k]
           qv[k] = 0.622 * pp * w
           #qv[k] = met.es(Td[k]+met.T00) / (met.Rv * (T[k]+met.T00))

        #print(z, th, p, qv, u, v)

        plot(0.,0., z, 0, th, p, qv, u, v, 'Sounding Data', output)

        
##################################################################################
# plot_cm1
#
# This plots a skewt at domain location xi,yi at time t=0 for a given CM1 dataset
# in grads format
#
def plot_cm1(path, filename, xi, yi,output):
  """Plot skewt from a Grads format CM1 output file

  :parameter _path: Path to CM1 dataset
  :type path: str
  :parameter _filename: Filename of dataset
  :type filename: str
  :parameter x1: X gridpoint to plot SkewT
  :parameter y1: Y gridpoint to plot SkewT
  :parameter output: Filename to save skewt plot

  This function plots a skewt from a CM1 output file.  
  This routine uses winds interpolated to the scalar
  gridpoints.  
  """
  f = cm1.CM1(path, filename)
  _z = f.dimZ[:] * 1000.   # km->m

  x = f.dimX[xi]
  y = f.dimY[yi]
  t = int(f.dimT[0])
        
  f.read3dMultStart(t)
  _th = f.read3dMult('th')
  _p = f.read3dMult('prs')
  _u = f.read3dMult('uinterp')
  _v = f.read3dMult('vinterp')
  _qv = f.read3dMult('qv')
  f.read3dMultStop()
  nk = len(_p[xi,yi,:])
  th = np.empty(nk+1, np.float32)
  p  = np.empty(nk+1, np.float32)
  u  = np.empty(nk+1, np.float32)
  v  = np.empty(nk+1, np.float32)
  qv = np.empty(nk+1, np.float32)
  z  = np.empty(nk+1, np.float32)
  th[1:] = _th[xi,yi,:]
  p[1:] = _p[xi,yi,:]
  u[1:] = _u[xi,yi,:]
  v[1:] = _v[xi,yi,:]
  qv[1:] = _qv[xi,yi,:]
  z[1:] = _z[:]

  # surface values
  p[0] = 100000.
  th[0]= 300.
  qv[0]= 0.014
  u[0] = u[1]
  v[0] = v[1]
  z[0] = 0.

  plot(x,y,z,t,th,p,qv,u,v,filename, output)

##################################################################################
# plot
#
# This is the main skewT plotting function for a single output page containing
# A skewt, hodograph and an information block (currently disabled).
#  
def plot(x, y, z, t, th, p, qv, u, v, title, output):
  """Plots Skew-T/Log-P diagrapms with hodograph

  The helper functions above facilitate loading data from
  various formats and then call this function.  If you have
  data in another format or arrays of data in python already,
  then this is the function you want to use.

  :parameter x: Unused
  :parameter y: Unused
  :parameter z: z grid mesh (1D)
  :parameter t: Unused
  :parameter th: Potential temperature at z points
  :parameter p: Pressure at z points
  :parameter qv: Water vapor mixing ratio at z points
  :parameter u: u winds at z points
  :parameter v: v winds at z points
  :parameter title: Title for plot
  :parameter output: Filename to save plot to

  """
  fig = plt.figure(1, figsize=(10, 8), dpi=300, edgecolor='k')
  ax1 = plt.subplot(121)
  plot_sounding_axes(ax1)
  plot_sounding(z, th, p, qv, u, v, ax1)
  ax2 = plt.subplot(222)
  plot_hodo_axes(ax2)
  plot_hodograph(z, u, v, ax2)
  #ax3 = fig.add_subplot(132)
  #plot_the_rest(x,y,z,t,th,p,qv,u,v,title,output)
  # plot_wind_axes?????
  plt.savefig(output, dpi=300,bbox_inches=0)
  plt.close()

def plot_sounding_axes(axes):
  """Plots Skew-T/Log-P axes

  This will plot isotherms, isobars, dry and moist adiabats, 
  lines of constant water vapor mixing ratio, labels and 
  setup the y axes to be reversed.

  :paramter axes: The axes to draw on
  """
  draw_isotherms(axes)
  draw_isobars(axes)
  draw_dry_adiabat(axes)
  draw_moist_adiabat(axes)
  draw_water_mix_ratio(axes)
  remove_tick_labels(axes)
  axes.axis([Tmin, Tmax, pbot, ptop])
  axes.set_ylim(axes.get_ylim()[::1])

def plot_wind_axes(axes):
  # plot wind barbs
  # TODO: also do storm-relative winds
  draw_wind_line()
  axes.set_axis_off()
  axes.axis([-1,1,pbot,ptop])

def plot_hodo_axes(axes):
  """Plot hodograph axes

  This will plot range arcs and labels for a hodograph plot
  """
  bounds = [-25,25,-25,25]
  axes.axis('equal')
  draw_hodograph(axes, bounds)
  remove_tick_labels(axes)
  axes.axis(bounds)

def plot_wind(z, p, u, v, axes, x=0):  
  for i in np.arange(0,len(z),1):
    if (p[i] > pt_plot):
      plt.barbs(x,p[i],u[i],v[i], length=5, linewidth=.5)

  
def plot_sounding(z, th, p, qv, u, v, axes):
  """Plot sounding data

  This plots temperature, dewpoint and wind data on a Skew-T/Log-P plot.
  This will also plot derived values such as wetbulb temperature and
  label the surface based LCL, LFC and EL.

  :parameter z: height values (1D array)
  :parameter th: potential temperature at z heights (1D array)
  :parameter p: pressure at z heights (1D array)
  :parameter qv: water vapor mixing ratio at z heights (1D array)
  :parameter u: U component of wind at z heights (1D array)
  :parameter v: V component of wind at z heights (1D array)
  :paramter axes: The axes instance to draw on
  """
  # calculate Temperature and dewpoint
  T = met.T(th,p) - met.T00                          # T (C)
  Td = met.Td(p, qv) - met.T00                       # Td (C)

  # calculate wetbulb temperature
  Twb = np.empty(len(z), np.float32)                  # Twb (C)
  for zlvl in range(len(z)):
    Twb[zlvl] = met.Twb(z, p, th, qv, z[zlvl])

  # Get surface parcel CAPE and temperature / height profiles
  pcl = met.CAPE(z, p, T+met.T00, qv, 1)        # CAPE
  T_parcel = pcl['t_p'] - met.T00                      # parcel T (C)
  T_vparcel = pcl['tv_p'] - met.T00                     # parcel Tv (C)
  T_venv = met.T(pcl['thv_env'], pcl['pp']) - met.T00  # Env Tv (C)

  # plot Temperature, dewpoint, wetbulb and lifted surface parcel profiles on skew axes
  axes.semilogy(T + skew(p), p, basey=math.e, color = 'black', linewidth = 1.5)
  axes.semilogy(Td + skew(p), p, basey=math.e, color = 'green', linewidth = 1.5)
  axes.semilogy(T_parcel + skew(pcl['pp']), pcl['pp'], basey=math.e, color='red', linewidth=1.0)
  axes.semilogy(Twb + skew(p), p, basey=math.e, color='blue', linewidth=0.5)

  # plot virtual temperature of environment and lifted parcel
  axes.semilogy(T_venv + skew(pcl['pp']), pcl['pp'], basey=math.e, color='black', linewidth=0.7, linestyle='--')
  axes.semilogy(T_vparcel + skew(pcl['pp']), pcl['pp'], basey=math.e, color='red', linewidth=0.7, linestyle='--')

  # Add labels for levels based on surface parcel
  label_m(Tmax-.5, pcl['lfcprs'], '--LFC', axes)
  label_m(Tmax-.5, pcl['lclprs'], '--LCL', axes)
  label_m(Tmax-.5, pcl['elprs'], '--EL', axes)
  label_m(Tmax-.5, pcl['ptops'], '--TOPS', axes)

  # plot labels for std heights
  for plvl in plevs_std:
    zlvl = pymeteo.interp.interp_height(z,p,plvl)
    label_m(Tmin-.5,plvl, str(int(zlvl)), axes)

  # plot wind barbs on left side of plot.  move this?  right side?
  #draw_wind_line()
  for i in np.arange(0,len(z),2):
    if (p[i] > pt_plot):
      plt.barbs(Tmin+4,p[i],u[i],v[i], length=5, linewidth=.5)

def plot_hodograph(z, u, v, axes):
  """Plot Hodograph data

  This plots u and v winds vs height on a hodograph.

  :parameter z: height values (1D array)
  :parameter u: U component of wind at z heights (1D array)
  :parameter v: V component of wind at z heights (1D array)
  :paramter axes: The axes instance to draw on
  """
  
  # plot hodograph
  z6km = 0
  while z[z6km] <= 12000:
    z6km += 1
  axes.plot(u[0:z6km],v[0:z6km], color='black', linewidth=1.5)

  for zlvl in np.arange(0,7000,1000):
    ulvl = pymeteo.interp.linear(z,u,zlvl)
    vlvl = pymeteo.interp.linear(z,v,zlvl)
    #print('calculating winds at height {0} = ({1},{2})'.format(zlvl,ulvl,vlvl))
    label_h2(ulvl+1,vlvl-1,str(zlvl/1000), 'black', 0, axes)
    axes.plot(ulvl,vlvl, color='black', markersize=5, marker='.')

  #TODO: fix this
  ucb = dyn.storm_motion_bunkers(u,v,z)
  axes.plot(ucb[0],ucb[1],markersize=4,color='black',marker='x')
  axes.plot(ucb[2],ucb[3],markersize=4,color='black',marker='x')

        
def calc_sounding_stats(_z, _th, _p, _qv):
  T = met.T(_th,_p)                        # T (K)
  pcl = met.CAPE(_z, _p, T, _qv, 1)        # CAPE
  mupcl = met.CAPE(_z, _p, T, _qv, 2)      # MUCAPE
  mlpcl = met.CAPE(_z, _p, T, _qv, 3)      # MLCAPE

  return (pcl,mupcl,mlpcl)

def calc_hodograph_stats(_z, _u, _v):

  ucb = dyn.storm_motion_bunkers(_u,_v,_z)

  # SRH
  srh01 = dyn.srh(_u, _v, _z, 0., 1000., ucb[0], ucb[1])
  srh03 = dyn.srh(_u, _v, _z, 0., 3000., ucb[0], ucb[1])
  erh01 = dyn.srh(_u, _v, _z, 0., 1000., 0., 0.)
  erh03 = dyn.srh(_u, _v, _z, 0., 3000., 0., 0.)
 
  shear01 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 0., 1000.))
  shear03 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 0., 3000.))
  shear06 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 0., 6000.))
  shear12 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 1000., 2000.))
  shear23 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 2000., 3000.))
  shear34 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 3000., 4000.))
  shear45 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 4000., 5000.))
  shear56 = dyn.uv_to_deg(*dyn.shear(_u, _v, _z, 5000., 6000.))

  dict = { 'bunkers' : ucb,
           'srh01'   : srh01,
           'srh03'   : srh03,
           'erh01'   : erh01,
           'erh03'   : erh03,
           's01'     : shear01,
           's03'     : shear03,
           's06'     : shear06,
           's12'     : shear12,
           's23'     : shear23,
           's34'     : shear34,
           's45'     : shear45,
           's56'     : shear56
         }

  return dict

################ UPDATE BELOW THIS LINE #############################
################                        #############################

def plot_the_rest(_x,_y,_z,_t,_th,_p,_qv,_u,_v,_title,_output):
 # pcl, mupcl, mlpcl = calc_sounding_stats(_z, _th, _p, _qv)
 # shear = calc_hodograph_stats(_z, _u, _v)



# brn = dyn.brn(_u, _v, _z, pcl['cape'])
  brn = 0

	# draw datablock
  ax4 = fig.add_subplot(224)
  ax4.set_axis_off()
  plt.axis([-1,1,-1,1])
  plt.text(0,1,_title, verticalalignment='top', horizontalalignment='center', weight='bold', fontsize=10)
  line = 'Sounding at location ' + str(_x) + ' km,' + str(_y) + ' km.  Time = ' + str(_t) + '.  '
  line += str(len(_z)) + ' vertical levels'
  plt.text(0,.85, line, verticalalignment='center', horizontalalignment='center', fontsize=5)

  cth,cr = dyn.uv_to_deg(ucb[0],ucb[1])
  line = 'Bunkers et al. (2000) right mover -> {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(cth),cr)
  plt.text(-1,.75, line, verticalalignment='center', horizontalalignment='left', fontsize=5)

  print_parcel_info('Surface Parcel', pcl, -1., .65)
  print_parcel_info('Most Unstable Parcel', mupcl, -0.5, .65)
  print_parcel_info('500 m Mixed Layer Parcel', mlpcl, 0., .65)

	# LCL, CCL, EL, convective temp?
	# other data?
	
  x = -1
  y = 0
  line = 'Hodograph'        
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '0-1 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear01[0]),shear01[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '0-3 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear03[0]),shear03[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '0-6 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear06[0]),shear06[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = 'SRH 0-1 : {0:d} m2/s2'.format(int(srh01))
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = 'SRH 0-3 : {0:d} m2/s2'.format(int(srh03))
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = 'ERH 0-1 : {0:d} m2/s2'.format(int(erh01))
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = 'ERH 0-3 : {0:d} m2/s2'.format(int(erh03))
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = 'BRN : {0:d}'.format(int(brn))
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '0-1 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear01[0]),shear01[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '1-2 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear12[0]),shear12[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '2-3 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear23[0]),shear23[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '3-4 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear34[0]),shear34[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '4-5 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear45[0]),shear45[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.05
  line = '5-6 km shear {0:3d}$^\circ$ {1:3.1f} m/s'.format(int(shear56[0]),shear56[1])
  plt.text(x,y, line, verticalalignment='center', horizontalalignment='left', fontsize=5)

	#plt.show()
  plt.savefig(_output, dpi=300,bbox_inches=0)
  plt.close()

def print_3col(name, value, unit, x, y):
   plt.text(x,y, name, verticalalignment='center', horizontalalignment='left', fontsize=5)
   plt.text(x+.25,y, value, verticalalignment='center', horizontalalignment='right', fontsize=5)
   plt.text(x+.3,y, unit, verticalalignment='center', horizontalalignment='left', fontsize=5)

def print_parcel_info(title, pcl, x, y):
  plt.text(x,y, title, verticalalignment='center', horizontalalignment='left', fontsize=5)
  y -= 0.065
  x += 0.02
  print_3col('CAPE', '{0}'.format(int(pcl['cape'])), 'J kg$^{-1}$', x, y)
  y -= 0.05
  print_3col('CIN', '{0}'.format(int(pcl['cin'])), 'J kg$^{-1}$', x, y)
  y -= 0.05
  print_3col('TOPS', '{0:4.2f}'.format(float(pcl['ztops'])), 'km', x, y)
  y -= 0.05
  print_3col(r'$\theta_e$', '{0:4.1f}'.format(float(pcl['theta_e'])), 'K', x, y)
  y -= 0.05
  print_3col('LI$_{MAX}$', '{0:3.1f}'.format(float(pcl['max_li'])), 'C', x, y)
  y -= 0.05
  print_3col('LI$_{500}$', '{0:3.1f}'.format(float(pcl['li500'])), 'C', x, y)
  y -= 0.05
  print_3col('LI$_{300}$', '{0:3.1f}'.format(float(pcl['li300'])), 'C', x, y)
  y -= 0.05
  print_3col('Parcel', '{0}'.format(int(pcl['prs']/100.)), 'mb', x, y)

########################### DONE BELOW LINE #########################################

def remove_tick_labels(axes):
  axes.tick_params(axis='x', top='off', bottom='off', which='both')#, labelsize=0)
  axes.tick_params(axis='y', left='off', right='off', which='both')#, labelsize=0)
  for xlabel_i in axes.get_xticklabels():
    xlabel_i.set_visible(False)
    xlabel_i.set_fontsize(0.0)
  for xlabel_i in axes.get_yticklabels():
    xlabel_i.set_fontsize(0.0)
    xlabel_i.set_visible(False)

def set_fontscalefactor(newfactor):
  fontscalefactor = newfactor

def label(x, y, s, c, r, axes):
	axes.text(x,y*100,s, verticalalignment='center', horizontalalignment='center', weight='bold', fontsize=5*fontscalefactor, color=c, rotation=r)

def label_h(x, y, s, c, r, axes):
	axes.text(x,y,s, verticalalignment='center', horizontalalignment='center', weight='normal', fontsize=7*fontscalefactor, color=c, rotation=r)

def label_h2(x, y, s, c, r, axes):
	axes.text(x,y,s, verticalalignment='center', horizontalalignment='center', weight='bold', fontsize=10*fontscalefactor, color=c, rotation=r)

def label_m(x, y, s, axes):
	axes.text(x,y,s, verticalalignment='center', horizontalalignment='right', fontsize=4*fontscalefactor)

#draw hodograph u-v space
def draw_hodograph(axes, bounds):
  xmin, xmax, ymin, ymax = bounds
  gmax = max(xmax,ymax)
  gmin = min(xmin,ymin)
	# draw u-v grid
  axes.plot([gmin,gmax],[0,0], color='black', linewidth=.5)
  axes.plot([0,0],[gmin,gmax], color='black', linewidth=.5)
  for u in np.arange(xmin+1,xmax):
    if (u%5==0) and (u != 0):
      label_h(u,-1,str(u),'black',0,axes)
  for v in np.arange(ymin+1,ymax):
    if (v%5==0) and (v != 0):
      label_h(-1,v,str(v),'black',0,axes)
	# draw speed rings
  for u in np.arange(5,math.sqrt(xmax**2+ymax**2)+1,5):
    axes.plot( *hodograph_circle(u), color='grey', linewidth=.3)

# helper function for circle points
def hodograph_circle(r):
	phi = np.arange(0., 2*math.pi, 0.01)
	return r*np.cos(phi), r*np.sin(phi)

# draws a vertical line axis upon which to draw wind barbs
def draw_wind_line(axes):
	wind_line = []
	for p in plevs_plot:
		wind_line.append(0)
	axes.semilogy(wind_line, plevs_plot, color='black', linewidth=.5)
	# plot circles at certain levels?
	for p in plevs_std:
		axes.semilogy(0,p, color='black', markersize=3, marker='.')

# Puts the skew in skew-T
def skew(p):
    """Puts the skew in skew-T

    :parameter p: pressure level of the point.

    This calculates the skew of the T axis for a point to plot.  
    This assumes a logarithmic y axes and uses the variable
    :py:data:skew_angle to determine the skew.  This is the 
    magic that turns a cartesian plot into a Skew-T/Log-p plot.
    """
    return skew_angle * np.log(met.p00/p)

# Draw isotherms on skew-T / log p axes
def draw_isotherms(axes):
    """Plot isotherms on axes

    :parameter axes: The axes to draw on
    :type axes: :py:class:`matplotlib.axes`

    This function draws isotherms every 10 C.
    """
    for T in np.arange(-150, 51, 10):
        axes.semilogy(T + skew(plevs_plot), plevs_plot, basey=math.e, color = 'grey', linewidth=.5)
    for T in np.arange(-40, 40, 10):
        label(T+skew(87500),875, str(T), 'red', 45, axes)
    for T in np.arange(-100, -20, 10):
        label(T+skew(17500),175, str(T), 'red', 45, axes)

def draw_isobars(axes):
    """Plot isobars on axes

    :parameter axes: The axes to draw on
    :type axes: :py:class:`matplotlib.axes`

    This function draws isobars at intervals of 2*dp.
    """
    for i in np.arange(pbot,ptop-1,-2*dp):
        axes.plot([Tmin, Tmax], [i,i], color = 'grey', linewidth = .3)
    for i in np.arange(ptickbot,ptop-1,-2*dp):
        axes.plot([Tmin, Tmax], [i,i], color = 'grey', linewidth = .5)
    for i in np.arange(1000,100,-50):
        label(-10-((1000-i)*.025),i,str(i),'black',0, axes)

def draw_dry_adiabat(axes):
    """Plot dry adiabats on axes

    :parameter axes: The axes to draw on
    :type axes: :py:class:`matplotlib.axes`

    This function calculates dry adiabats
    and plots these lines.  Adiabats are calculated 
    every 10 K
    """
    for Tk in met.T00 + np.arange(-40, 210, 10):
        dry_adiabat = met.T(Tk,plevs_plot) - met.T00 + skew(plevs_plot)
        axes.semilogy(dry_adiabat, plevs_plot, basey=math.e, color = 'grey', linewidth = .5)

    for T in np.arange(-20, 150, 10):
        p = (600. - 3.5*T)*100.
        x = met.T(T+met.T00,p) -met.T00 + skew(p)
        x1 = met.T(T+met.T00,p+.5*dp_plot) -met.T00 + skew(p+.5*dp_plot)
        x2 = met.T(T+met.T00,p-.5*dp_plot) -met.T00 + skew(p-.5*dp_plot)
        dx = x2-x1
        theta = math.atan2(-dp_plot,-dx) * 180/math.pi +37
        label(x,p/100,str(T),'black',theta, axes)


def draw_moist_adiabat(axes):
    """Plot moist adiabats on axes

    :parameter axes: The axes to draw on
    :type axes: :py:class:`matplotlib.axes`

    This function calculates moist adiabats
    and plots these lines.  Adiabats are calculated for
    values of T at 1000mb from -15 to 45 C every 5 C between
    -15 and 10 C and every 2.5 C between 12.5 and 45 C.
    """
    ps_blo = [p for p in plevs_plot if p > 100000]
    ps_blo.reverse()
    ps = [p for p in plevs_plot2 if p < 100000]
    Temps = np.concatenate((np.arange(-15.,10.1,5.),np.arange(12.5,45.1,2.5)))
    for T in Temps:
        T_1000 = T = T + met.T00
        moist_adiabat = []
        # work backwards from 1000mb
        for p in ps_blo:
            T += met.dTdp_moist(T,p) * dp_plot
            moist_adiabat.append(T - met.T00 + skew(p))
        #reverse list order
        moist_adiabat.reverse()
        # insert 1000mb point
        T = T_1000
        moist_adiabat.append(T - met.T00)
        # work forwards from 1000mb
        for p in ps:
            T -= met.dTdp_moist(T,p) * dp_plot
            moist_adiabat.append(T - met.T00 + skew(p))
            # draw labels
            if (p == 22000):
                if (T_1000 >= met.T00 and T_1000 <= 30+met.T00):
                    label(T-met.T00+skew(p),p/100,str(int(T_1000-met.T00)),'green', 0, axes)
            axes.semilogy(moist_adiabat, plevs_plot2, basey=math.e, color = 'grey', linewidth = .5)


def draw_water_mix_ratio(axes):
    """Plot lines of constant water vapor mixing ratio on axes

    :parameter axes: The axes to draw on
    :type axes: :py:class:`matplotlib.axes`

    This function calculates isolines of constant water vapor
    mixing ratio and plots these lines.  Values of w calculated
    are given by the list variable w.
    """
    #TODO: put w and the top plevel for plotting somewhere configurable
    w = [0.2,0.4,0.8,1,2,3,4,6,8,10,14,18,24,32,40]
    ps = [p for p in plevs if p>=20000 and p<=105000]
    for W in w:
        water_mix = []
        for p in ps:
            T = TMR(W,p/100.) 
            water_mix.append(T + skew(p))
        axes.semilogy(water_mix, ps, basey=math.e, color = 'grey', linestyle = '--', linewidth = .5)

        # Label the isoline
        T = TMR(W,1075.)
        label(T+skew(107500.), 1075, str(W), 'black', -15, axes)


def TMR(W, p):
  # Computes temperature on mixing ratio w at pressure p.
  # TMR in C, w in g/kg dry air, p in millibars.
  # TODO: change this to something else?
  x = np.log10(W * p / (622 + W))
  TMR = 10 ** (0.0498646455 * x + 2.4082965) - 280.23475 + 38.9114 * ((10 ** (0.0915 * x) - 1.2035) ** 2)
  return TMR

