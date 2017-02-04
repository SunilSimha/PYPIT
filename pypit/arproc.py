from __future__ import (print_function, absolute_import, division, unicode_literals)

import numpy as np
from scipy.signal import savgol_filter
import scipy.signal as signal
import scipy.ndimage as ndimage
from matplotlib import pyplot as plt
from pypit import arextract
from pypit import arflat
from pypit import arlris
from pypit import armsgs
from pypit import artrace
from pypit import arutils
from pypit import arparse as settings
from pypit import arspecobj
from pypit import arqa
from pypit import arpca
from pypit import arwave

from pypit import ardebug as debugger

# Logging
msgs = armsgs.get_logger()


def background_subtraction(slf, sciframe, varframe, k=3, crsigma=20.0, maskval=-999999.9, nsample=1):
    """
    Idea for background subtraction:
    (1) Assume that all pixels are background and (by considering the tilts) create an array of pixel flux vs pixel wavelength.
    (2) Step along pixel wavelength, and mask out the N pixels (where N ~ 5) that have the maximum flux in each "pixel" bin.
    (3) At each pixel bin, perform a robust regression with the remaining values until all values in a given bin are consistent with a constant value.
    (4) Using all non-masked values, perform a least-squares spline fit to the points. This corresponds to the background spectrum
    (5) Reconstruct the background image by accounting for the tilts.

    Perform a background subtraction on the science frame by
    fitting a b-spline to the background.

    This routine will (probably) work poorly if the order traces overlap (of course)
    """
    from pypit import arcyextract
    from pypit import arcyutils
    from pypit import arcyproc
    errframe = np.sqrt(varframe)
    retframe = np.zeros_like(sciframe)
    norders = slf._lordloc.shape[1]
    # Look at the end corners of the detector to get detector size in the dispersion direction
    xstr = slf._pixlocn[0,0,0]-slf._pixlocn[0,0,2]/2.0
    xfin = slf._pixlocn[-1,-1,]+slf._pixlocn[-1,-1,2]/2.0
    xint = slf._pixlocn[:,0,0]
    # Find which pixels are within the order edges
    msgs.info("Identifying pixels within each order")
    ordpix = arcyutils.order_pixels(slf._pixlocn, slf._lordloc, slf._rordloc)
    allordpix = ordpix.copy()
    msgs.info("Applying bad pixel mask")
    ordpix *= (1-slf._bpix.astype(np.int))
    whord = np.where(ordpix != 0)
#    msgs.info("Masking cosmic ray hits")
#    crr_id = arcyutils.crreject(sciframe/np.median(sciframe[whord]))
#    cruse = np.abs(crr_id/sciframe)[whord]
#    medcr = np.median(cruse)
#    madcr = 1.4826*np.median(np.abs(cruse-medcr))
#    whcrt = np.where(cruse>medcr+crsigma*madcr)
#    whcrr = (whord[0][whcrt],whord[1][whcrt])
#    msgs.info("Identified {0:d} pixels affected by cosmic rays within orders in the science frame".format(whord[0].size))
#    if whcrr[0].size != 0: ordpix[whcrr] = 0
#	temp = sciframe.copy()
#	temp[whcrr] = 0.0
#	arutils.ds9plot(temp.astype(np.float))
    msgs.info("Rectifying the orders to estimate the background locations")
    msgs.work("Multiprocess this step to make it faster")
    badorders = np.zeros(norders)
    ordpixnew = np.zeros_like(ordpix)
    for o in range(norders):
        # Rectify this order
        recframe = arcyextract.rectify(sciframe, ordpix, slf._pixcen[:,o], slf._lordpix[:,o], slf._rordpix[:,o], slf._pixwid[o], maskval)
        recerror = arcyextract.rectify(errframe, ordpix, slf._pixcen[:,o], slf._lordpix[:,o], slf._rordpix[:,o], slf._pixwid[o], maskval)
        #recmask = np.ones(recframe.shape, dtype=np.int)
        #wmsk = np.where(recframe==maskval)
        #recmask[wmsk] = 0
        #arutils.ds9plot(recframe.astype(np.float))
        #arutils.ds9plot(recerror.astype(np.float))
        #arutils.ds9plot((recframe/recerror).astype(np.float))
        # Create a mask where there is significant flux from the object
        #flux = arcyextract.maskedaverage_order(recframe, np.ones_like(recframe), maskval)
        #plt.plot(np.arange(flux.size),flux,'k-',drawstyle='steps')
        # At least three pixels in a given row need to be detected at 2 sigma
        rowd = np.where( ((recerror!=0.0) & (recframe/recerror > 2.0)).astype(np.int).sum(axis=1) >= 3 )
        w = np.ix_(rowd[0],np.arange(recframe.shape[1]))
        #arutils.ds9plot(recframe.astype(np.float))
        #objprof = arcyextract.maskedaverage_order(recframe[w], recerror[w]**2, maskval)
        recframesmth = arcyproc.smooth_gaussmask(recframe[w], maskval, 4.0)
        # Sort the pixels along the spatial direction based on their flux

        # Select only pixels with a flux consistent with a constant valueIdentify the most common columns are




        #arutils.ds9plot(recframe[w].astype(np.float))
        #arutils.ds9plot(recframesmth.astype(np.float))
        objprofm = arcyextract.maskedmedian_order(recframesmth, maskval)
        if (len(objprofm) < slf._pixwid[o]/3) or (len(objprofm) <= 5):
            badorders[o] = 1
            continue
        #plt.plot(np.arange(objprof.size),objprof,'r-',drawstyle='steps')
        #plt.plot(np.arange(objprofm.size),objprofm,'k-',drawstyle='steps')
        # Reject the flux from the 3 highest S/N pixels (originally required to be included)
        xarray = np.arange(objprofm.size)
        profmask = np.zeros(objprofm.size,dtype=np.int)
        w = np.argsort(objprofm)[-3:]
        profmask[w] = 1
        # Exclude the end points
        profmask[0] = 1
        profmask[-1] = 1
        profmask, coeff = arutils.robust_polyfit(xarray, objprofm, 0, maxone=True, sigma=2.0, function="polynomial", initialmask=profmask, forceimask=True)
        #bgfit = arutils.func_val(coeff,xarray,"polynomial")
        #plt.plot(xarray,bgfit,'r-')
        w = np.where(profmask==0)
        #plt.plot(xarray[w],bgfit[w],'go')
        #plt.axis([0,30,0,np.max(objprofm)])
        #plt.show()
        #plt.clf()
        bgloc = np.zeros_like(recframe)
        bgloc[:,w] = 1.0
        # Undo the rectification
        #arutils.ds9plot(bgloc)
        unrecmask = arcyextract.rectify_undo(bgloc, slf._pixcen[:,o], slf._lordpix[:,o], slf._rordpix[:,o], slf._pixwid[o], maskval, sciframe.shape[0], sciframe.shape[1])
        #arutils.ds9plot(unrecmask)
        # Apply the mask to master mask
        ordpixnew += unrecmask.copy()

    # Update ordpix
    msgs.info("Masking object to determine background level")
    ordpix *= ordpixnew

    msgs.work("Plot/save background locations")
    msgs.work("Deal with bad orders")
    #arutils.ds9plot(ordpix.astype(np.float))

    msgs.info("Fitting and reconstructing background")
    # Create the over-sampled array of points in the dispersion direction (detector)
    ncoeff, k = sciframe.shape[0], 1
    xmod = np.linspace(xstr,xfin,sciframe.shape[0]*nsample)
    ycen = 0.5*(slf._lordloc + slf._rordloc)
    """
    The b-spline algorithm takes *far* too long to compute for the entire order simultaneously.
    An iteration procedure is now needed to step along the order and fit each position as you step along the order.

    Speed this up by selecting only considering pixels inside the given lordpix/rordpix of each order, rather than grabbing all xpix and ypix
    """
    bgmod = np.zeros_like(sciframe)
    polyorder, repeat = 9, 1
    for o in range(norders):
        #if o < 3 or o > norders-5: continue
        xpix, ypix = np.where(ordpix==o+1)
        print("Preparing", o+1)
        xbarr, ybarr = arcyutils.prepare_bsplfit(sciframe, slf._pixlocn, slf._tilts[:,o], xmod, ycen[:,o], xpix, ypix)
        xapix, yapix = np.where(allordpix==o+1)
        xball = arcyproc.prepare_bgmodel(sciframe, slf._pixlocn, slf._tilts[:,o], xmod, ycen[:,o], xapix, yapix)
        ebarr = np.ones_like(xbarr)
        print("Fitting", o+1, xbarr.size)
        argsrt = np.argsort(xbarr,kind='mergesort')
        polypoints = 3*slf._pixwid[o]
        fitfunc = arcyutils.polyfit_scan(xbarr[argsrt], ybarr[argsrt], ebarr, maskval, polyorder, polypoints, repeat)
        fitfunc_model = np.interp(xball, xbarr[argsrt], fitfunc)
        bgmod += arcyproc.background_model(fitfunc_model, xapix, yapix, sciframe.shape[0], sciframe.shape[1])
#		np.save("bspl/xbarr_ord{0:d}".format(o+1),xbarr)
#		np.save("bspl/ybarr_ord{0:d}".format(o+1),ybarr)
#		np.save("bspl/ebarr_ord{0:d}".format(o+1),ebarr)
#		print min(np.min(xbarr),xstr), max(np.max(xbarr),xfin), ncoeff, k
#		np.save("bspl/pixlocn_ord{0:d}".format(o+1),slf._pixlocn)
#		np.save("bspl/tilts_ord{0:d}".format(o+1),slf._tilts[:,o])
#		np.save("bspl/xmod_ord{0:d}".format(o+1),xmod)
#		np.save("bspl/ycen_ord{0:d}".format(o+1),ycen[:,o])
#		np.save("bspl/xpix_ord{0:d}".format(o+1),xpix)
#		np.save("bspl/ypix_ord{0:d}".format(o+1),ypix)
#		print "saved all!"
#		#mod_yarr = cybspline.bspline_fit(xmod, xbarr, ybarr, ebarr, min(np.min(xbarr),xstr), max(np.max(xbarr),xfin), ncoeff, k)
#		bgmod += arcyutils.bspline_fitmod(xbarr, ybarr, ebarr, min(np.min(xbarr),xstr), max(np.max(xbarr),xfin), ncoeff, k, slf._pixlocn, slf._tilts[:,o], xmod, ycen[:,o], xpix, ypix)

    arutils.ds9plot(bgmod.astype(np.float))
    arutils.ds9plot((sciframe-bgmod).astype(np.float))

    #exsci, exerr = arcyextract.extract_weighted(frame, error, badpixmask, pixcen[:,o], piycen[:,o], slf._pixlocn, ordtilt[:,o], ordxcen[:,o], ordycen[:,o], ordwid[:,o], ordwnum[o], ordlen[o], ordnum[o], argf_interpnum)

# 	ordcen = 0.5*(slf._lordloc + slf._rordloc)
# 	ordwid = np.ceil(np.median(np.abs(slf._lordloc - slf._rordloc),axis=0)).astype(np.int)/2
# 	cord_pix = artrace.phys_to_pix(ordcen, slf._pixlocn, 1)
# 	print cord_pix
# 	print ordwid
# 	test_rect = arcyextract.rectify_fast(sciframe, cord_pix, ordwid, -999999.9)
# 	arutils.ds9plot(test_rect)
# 	for o in range(norders):
# 		pass


    assert(False)
    # Mask out ordpix pixels where there is target flux
    ordpix = None
    # Prepare and fit the sky background pixels in every order
    msgs.work("Multiprocess this step to make it faster")
    skybg = np.zeros_like(sciframe)
    for o in range(norders):
        xpix, ypix = np.where(ordpix==1+o)
        msgs.info("Preparing sky pixels in order {0:d}/{1:d} for a b-spline fit".format(o+1,norders))
        #xbarr, ybarr = cybspline.prepare_bsplfit(arc, pixmap, tilts, xmod, ycen, xpix, ypix)
        msgs.info("Performing b-spline fir to oversampled sky background in order {0:d}/{1:d}".format(o+1,norders))
        #ncoeff, k = flt.shape[0], 1
        #mod_yarr = cybspline.bspline_fit(xmod, xbarr, ybarr, ebarr, min(np.min(xbarr),xstr), max(np.max(xbarr),xfin), ncoeff, k)
        #skybg += cybspline.bspline_fitmod(xbarr, ybarr, ebarr, min(np.min(xbarr),xstr), max(np.max(xbarr),xfin), ncoeff, k, pixmap, tilts, xmod, ycen, xpix, ypix)

    # Subtract the background
    msgs.info("Subtracting the sky background from the science frame")
    return sciframe-skybg, skybg


def badpix(det, frame, sigdev=10.0):
    """
    frame is a master bias frame
    sigdev is the number of standard deviations away from the median that a pixel needs to be in order to be classified as a bad pixel
    """
    dnum = settings.get_dnum(det)
    bpix = np.zeros_like(frame, dtype=np.int)
    subfr, tframe, temp = None, None, None
    for i in range(settings.spect[dnum]['numamplifiers']):
        datasec = "datasec{0:02d}".format(i+1)
        x0, x1 = settings.spect[dnum][datasec][0][0], settings.spect[dnum][datasec][0][1]
        y0, y1 = settings.spect[dnum][datasec][1][0], settings.spect[dnum][datasec][1][1]
        xv = np.arange(x0, x1)
        yv = np.arange(y0, y1)
        # Construct an array with the rows and columns to be extracted
        w = np.ix_(xv,yv)
        tframe = frame[w]
        temp = np.abs(np.median(tframe)-tframe)
        sigval = max(np.median(temp)*1.4826, 1.4826)
        ws = np.where(temp > sigdev*sigval)
        subfr = np.zeros(tframe.shape, dtype=np.int)
        subfr[ws] = 1
        bpix[w] = subfr
    del subfr, tframe, temp
    # Finally, trim the bad pixel frame
    bpix = trim(bpix, det)
    msgs.info("Identified {0:d} bad pixels".format(int(np.sum(bpix))))
    return bpix


def bg_subtraction(slf, det, sciframe, varframe, crpix, tracemask=None,
                   rejsigma=3.0, maskval=-999999.9):
    """ Extract a science target and background flux
    :param slf:
    :param sciframe:
    :param varframe:
    :return:
    """
    from pypit import arcyutils
    from pypit import arcyproc
    # Set some starting parameters (maybe make these available to the user)
    msgs.work("Should these parameters be made available to the user?")
    polyorder, repeat = 5, 1
    # Begin the algorithm
    errframe = np.sqrt(varframe)
    norders = slf._lordloc[det-1].shape[1]
    # Find which pixels are within the order edges
    msgs.info("Identifying pixels within each order")
    ordpix = arcyutils.order_pixels(slf._pixlocn[det-1],
                                    slf._lordloc[det-1]*0.95+slf._rordloc[det-1]*0.05,
                                    slf._lordloc[det-1]*0.05+slf._rordloc[det-1]*0.95)
    msgs.info("Applying bad pixel mask")
    ordpix *= (1-slf._bpix[det-1].astype(np.int)) * (1-crpix.astype(np.int))
    if tracemask is not None: ordpix *= (1-tracemask.astype(np.int))
    # Construct an array of pixels to be fit with a spline
    msgs.bug("Remember to include the following in a loop over order number")
    #whord = np.where(ordpix != 0)
    o = 0 # order=1
    whord = np.where(ordpix == o+1)
    tilts = slf._tilts[det-1].copy()
    xvpix  = tilts[whord]
    scipix = sciframe[whord]
    varpix = varframe[whord]
    xargsrt = np.argsort(xvpix,kind='mergesort')
    sxvpix  = xvpix[xargsrt]
    sscipix = scipix[xargsrt]
    svarpix = varpix[xargsrt]
    # Reject deviant pixels -- step through every 1.0/sciframe.shape[0] in sxvpix and reject significantly deviant pixels
    edges = np.linspace(min(0.0,np.min(sxvpix)),max(1.0,np.max(sxvpix)),sciframe.shape[0])
    fitcls = np.zeros(sciframe.shape[0])
    #if tracemask is None:
    if True:
        maskpix = np.zeros(sxvpix.size)
        msgs.info("Identifying pixels containing the science target")
        msgs.work("Speed up this step in cython")
        for i in range(sciframe.shape[0]-1):
            wpix = np.where((sxvpix>=edges[i]) & (sxvpix<=edges[i+1]))
            if (wpix[0].size>5):
                txpix = sxvpix[wpix]
                typix = sscipix[wpix]
                msk, cf = arutils.robust_polyfit(txpix, typix, 0, sigma=rejsigma)
                maskpix[wpix] = msk
                #fitcls[i] = cf[0]
                wgd=np.where(msk==0)
                szt = np.size(wgd[0])
                if szt > 8:
                    fitcls[i] = np.mean(typix[wgd][szt/2-3:szt/2+4]) # Average the 7 middle pixels
                    #fitcls[i] = np.mean(np.random.shuffle(typix[wgd])[:5]) # Average the 5 random pixels
                else:
                    fitcls[i] = cf[0]
    else:
        msgs.work("Speed up this step in cython")
        for i in range(sciframe.shape[0]-1):
            wpix = np.where((sxvpix>=edges[i]) & (sxvpix<=edges[i+1]))
            typix = sscipix[wpix]
            szt = typix.size
            if szt > 8:
                fitcls[i] = np.mean(typix[szt/2-3:szt/2+4]) # Average the 7 middle pixels
            elif szt != 0:
                fitcls[i] = np.mean(typix)
            else:
                fitcls[i] = 0.0
        # Trace the sky lines to get a better estimate of the tilts
        scicopy = sciframe.copy()
        scicopy[np.where(ordpix==0)] = maskval
        scitilts, _ = artrace.model_tilt(slf, det, scicopy, guesstilts=tilts.copy(), censpec=fitcls, maskval=maskval, plotQA=True)
        xvpix  = scitilts[whord]
        scipix = sciframe[whord]
        varpix = varframe[whord]
        mskpix = tracemask[whord]
        xargsrt = np.argsort(xvpix,kind='mergesort')
        sxvpix  = xvpix[xargsrt]
        sscipix = scipix[xargsrt]
        svarpix = varpix[xargsrt]
        maskpix = mskpix[xargsrt]
    # Check the mask is reasonable
    scimask = sciframe.copy()
    rxargsrt = np.argsort(xargsrt,kind='mergesort')
    scimask[whord] *= (1.0-maskpix)[rxargsrt]
    #arutils.ds9plot(scimask)
    # Now trace the sky lines to get a better estimate of the spectral tilt during the observations
    scifrcp = scimask.copy()
    scifrcp[whord] += (maskval*maskpix)[rxargsrt]
    scifrcp[np.where(ordpix == 0)] = maskval
    # Check tilts?
    '''
    if msgs._debug['sky_tilts']:
        gdp = scifrcp != maskval
        debugger.xplot(tilts[gdp]*tilts.shape[0], scifrcp[gdp], scatter=True)
        if False:
            plt.clf()
            ax = plt.gca()
            ax.scatter(tilts[1749,:], scifrcp[1749,:], color='green')
            ax.scatter(tilts[1750,:], scifrcp[1750,:], color='blue')
            ax.scatter(tilts[1751,:], scifrcp[1751,:], color='red')
            ax.scatter(tilts[1752,:], scifrcp[1752,:], color='orange')
            ax.set_ylim(0., 3000)
            plt.show()
        debugger.set_trace()
    '''
    #
    msgs.info("Fitting sky background spectrum")
    if settings.argflag['reduce']['skysub']['method'].lower() == 'polyscan':
        polypoints = 5
        nsmth = 15
        bgmodel = arcyproc.polyscan_fitsky(tilts.copy(), scifrcp.copy(), 1.0/errframe, maskval, polyorder, polypoints, nsmth, repeat)
        bgpix = bgmodel[whord]
        sbgpix = bgpix[xargsrt]
        wbg = np.where(sbgpix != maskval)
        # Smooth this spectrum
        polyorder = 1
        xpix = sxvpix[wbg]
        maxdiff = np.sort(xpix[1:]-xpix[:-1])[xpix.size-sciframe.shape[0]-1] # only include the next pixel in the fit if it is less than 10x the median difference between all pixels
        msgs.info("Generating sky background image")
        if msgs._debug['sky_sub']:
            debugger.set_trace()
            debugger.xplot(sxvpix[wbg]*tilts.shape[0], sbgpix[wbg], scatter=True)
        bgscan = arcyutils.polyfit_scan_lim(sxvpix[wbg], sbgpix[wbg].copy(), np.ones(wbg[0].size,dtype=np.float), maskval, polyorder, sciframe.shape[1]/3, repeat, maxdiff)
        # Restrict to good values
        gdscan = bgscan != maskval
        if msgs._debug['sky_sub']:
            debugger.set_trace()
            debugger.xplot(sxvpix[wbg[0][gdscan]]*tilts.shape[0], sbgpix[wbg[0][gdscan]], scatter=True)
        if np.sum(~gdscan) > 0:
            msgs.warn("At least one masked value in bgscan")
        # Generate
        bgframe = np.interp(tilts.flatten(), sxvpix[wbg[0][gdscan]], bgscan[gdscan]).reshape(tilts.shape)
    elif settings.argflag['reduce']['skysub']['method'].lower() == 'bspline':
        msgs.info("Using bspline sky subtraction")
        gdp = scifrcp != maskval
        srt = np.argsort(tilts[gdp])
        bspl = arutils.func_fit(tilts[gdp][srt], scifrcp[gdp][srt], 'bspline', 3,
                                **settings.argflag['reduce']['skysub']['bspline'])
        bgf_flat = arutils.func_val(bspl, tilts.flatten(), 'bspline')
        bgframe = bgf_flat.reshape(tilts.shape)
        if msgs._debug['sky_sub']:
            gdp = scifrcp != maskval
            srt = np.argsort(tilts.flatten())
            plt.clf()
            ax = plt.gca()
            ax.scatter(tilts[gdp]*tilts.shape[0], scifrcp[gdp], marker='o')
            ax.plot(tilts.flatten()[srt]*tilts.shape[0], bgf_flat[srt], 'r-')
            plt.show()
            debugger.set_trace()
    else:
        msgs.error('Not ready for this method for skysub {:s}'.format(
                settings.argflag['reduce']['skysub']['method'].lower()))
    if np.sum(np.isnan(bgframe)) > 0:
        msgs.warn("NAN in bgframe.  Replacing with 0")
        bad = np.isnan(bgframe)
        bgframe[bad] = 0.
    if msgs._debug['sky_sub']:
        debugger.set_trace()
    # Plot to make sure that the result is good
    #arutils.ds9plot(bgframe)
    #arutils.ds9plot(sciframe-bgframe)
    return bgframe


def error_frame_postext(sciframe, idx, fitsdict):
    # Dark Current noise
    dnoise = settings.spect['det']['darkcurr'] * float(fitsdict["exptime"][idx])/3600.0
    # The effective read noise
    rnoise = settings.spect['det']['ronoise']**2 + (0.5*settings.spect['det']['gain'])**2
    errframe = np.zeros_like(sciframe)
    w = np.where(sciframe != -999999.9)
    errframe[w] = np.sqrt(sciframe[w] + rnoise + dnoise)
    w = np.where(sciframe == -999999.9)
    errframe[w] = 999999.9
    return errframe


def get_datasec_trimmed(slf, fitsdict, det, scidx):
    """
     Generate a frame that identifies each pixel to an amplifier, and then trim it to the data sections.
     This frame can be used to later identify which trimmed pixels correspond to which amplifier

    Parameters
    ----------
    slf : class
      An instance of the ScienceExposure class
    fitsdict : dict
      Contains relevant information from fits header files
    det : int
      Detector number, starts at 1
    scidx : int
      Index of science frame

    Returns
    -------
    fitsdict : dict
      Updates to the input fitsdict
    """
    dnum = settings.get_dnum(det)

    # Get naxis0, naxis1, datasec, oscansec, ampsec for specific instruments
    if settings.argflag['run']['spectrograph'] in ['lris_blue', 'lris_red']:
        msgs.info("Parsing datasec and oscansec from headers")
        temp, head0, secs = arlris.read_lris(fitsdict['directory'][scidx]+
                                             fitsdict['filename'][scidx],
                                             det)
        # Naxis
        fitsdict['naxis0'][scidx] = temp.shape[0]
        fitsdict['naxis1'][scidx] = temp.shape[1]
        # Loop on amplifiers
        for kk in range(settings.spect[dnum]['numamplifiers']):
            datasec = "datasec{0:02d}".format(kk+1)
            settings.spect[dnum][datasec] = settings.load_sections(secs[0][kk])
            oscansec = "oscansec{0:02d}".format(kk+1)
            settings.spect[dnum][oscansec] = settings.load_sections(secs[1][kk])
    # For convenience
    naxis0, naxis1 = int(fitsdict['naxis0'][scidx]), int(fitsdict['naxis1'][scidx])
    # Initialize the returned array
    retarr = np.zeros((naxis0, naxis1))
    for i in range(settings.spect[dnum]['numamplifiers']):
        datasec = "datasec{0:02d}".format(i+1)
        x0, x1 = settings.spect[dnum][datasec][0][0], settings.spect[dnum][datasec][0][1]
        y0, y1 = settings.spect[dnum][datasec][1][0], settings.spect[dnum][datasec][1][1]
        if x0 < 0: x0 += naxis0
        if x1 <= 0: x1 += naxis0
        if y0 < 0: y0 += naxis1
        if y1 <= 0: y1 += naxis1
        # Fill in the pixels for this amplifier
        xv = np.arange(x0, x1)
        yv = np.arange(y0, y1)
        w = np.ix_(xv, yv)
        try:
            retarr[w] = i+1
        except IndexError:
            debugger.set_trace()
        # Save these locations for trimming
        if i == 0:
            xfin = xv.copy()
            yfin = yv.copy()
        else:
            xfin = np.unique(np.append(xfin, xv.copy()))
            yfin = np.unique(np.append(yfin, yv.copy()))
    # Construct and array with the rows and columns to be extracted
    w = np.ix_(xfin, yfin)
    if slf is not None:
        slf._datasec[det-1] = retarr[w]
    return


def get_wscale(slf):
    """
    This routine calculates the wavelength array based on the sampling size (in km/s) of each pixel.
    It conveniently assumes a standard reference wavelength of 911.75348 A
    """

    lam0 = 911.75348
    step = 1.0 + settings.argflag['reduce']['pixelsize']/299792.458
    # Determine the number of pixels from lam0 that need to be taken to reach the minimum wavelength of the spectrum
    msgs.work("No orders should be masked -- remove this code when the auto wavelength ID routine is fixed, and properly extrapolates.")
    w = np.where(slf._waveids!=-999999.9)
    nmin = int(np.log10(np.min(slf._waveids[w])/lam0)/np.log10(step) )
    nmax = int(1.0 + np.log10(np.max(slf._waveids[w])/lam0)/np.log10(step) ) # 1.0+ is to round up
    wave = np.min(slf._waveids[w]) * (step**np.arange(1+nmax-nmin))
    msgs.info("Extracted wavelength range will be: {0:.5f} - {1:.5f}".format(wave.min(),wave.max()))
    msgs.info("Total number of spectral pixels in the extracted spectrum will be: {0:d}".format(1+nmax-nmin))
    return wave


def reduce_frame(slf, sciframe, scidx, fitsdict, det, standard=False):
    """ Run standard extraction steps on a frame

    Parameters
    ----------
    sciframe : image
      Bias subtracted image (using arload.load_frame)
    scidx : int
      Index of the frame
    fitsdict : dict
      Contains relevant information from fits header files
    det : int
      Detector index
    standard : bool, optional
      Standard star frame?
    """
    # Check inputs
    if not isinstance(scidx,int):
        raise IOError("scidx needs to be an int")
    # Convert ADUs to electrons
    sciframe *= gain_frame(slf,det) #settings.spect['det'][det-1]['gain']
    # Mask
    slf._scimask[det-1] = np.zeros_like(sciframe).astype(int)
    msgs.info("Masking bad pixels")
    slf.update_sci_pixmask(det, slf._bpix[det-1], 'BadPix')
    # Variance
    msgs.info("Generate raw variance frame (from detected counts [flat fielded])")
    rawvarframe = variance_frame(slf, det, sciframe, scidx, fitsdict)
    ###############
    # Subtract off the scattered light from the image
    msgs.work("Scattered light subtraction is not yet implemented...")
    ###############
    # Flat field the science frame (and variance)
    if settings.argflag['reduce']['flatfield']['perform']:
        msgs.info("Flat fielding the science frame")
        sciframe, rawvarframe = arflat.flatfield(slf, sciframe, slf._mspixelflatnrm[det-1], det, varframe=rawvarframe)
    else:
        msgs.info("Not performing a flat field calibration")
    if not standard:
        slf._sciframe[det-1] = sciframe
        slf._rawvarframe[det-1] = rawvarframe
    ###############
    # Identify cosmic rays
    msgs.work("Include L.A.Cosmic arguments in the settings files")
    if True: crmask = lacosmic(slf, fitsdict, det, sciframe, scidx, grow=1.5)
    else: crmask = np.zeros(sciframe.shape)
    # Mask
    slf.update_sci_pixmask(det, crmask, 'CR')
    msgs.work("For now, perform extraction -- really should do this after the flexure+heliocentric correction")
    ###############
    # Estimate Sky Background
    if settings.argflag['reduce']['skysub']['perform']:
        # Perform an iterative background/science extraction
        if msgs._debug['obj_profile'] and False:
            msgs.warn("Reading background from 2D image on disk")
            from astropy.io import fits
            datfil = settings.argflag['run']['directory']['science']+'/spec2d_{:s}.fits'.format(slf._basename.replace(":","_"))
            hdu = fits.open(datfil)
            bgframe = hdu[1].data - hdu[2].data
        else:
            msgs.info("First estimate of the sky background")
            bgframe = bg_subtraction(slf, det, sciframe, rawvarframe, crmask)
        #bgframe = bg_subtraction(slf, det, sciframe, varframe, crmask)
        modelvarframe = variance_frame(slf, det, sciframe, scidx, fitsdict, skyframe=bgframe)
        if not standard: # Need to save
            slf._modelvarframe[det-1] = modelvarframe
            slf._bgframe[det-1] = bgframe
    ###############
    # Estimate trace of science objects
    scitrace = artrace.trace_object(slf, det, sciframe-bgframe, modelvarframe, crmask, doqa=(not standard))
    if scitrace is None:
        msgs.info("Not performing extraction for science frame"+msgs.newline()+fitsdict['filename'][scidx[0]])
        debugger.set_trace()
        #continue
    ###############
    # Finalize the Sky Background image
    if settings.argflag['reduce']['skysub']['perform'] & (scitrace['nobj']>0):
        # Perform an iterative background/science extraction
        msgs.info("Finalizing the sky background image")
        trcmask = scitrace['object'].sum(axis=2)
        trcmask[np.where(trcmask>0.0)] = 1.0
        if not msgs._debug['obj_profile']:
            bgframe = bg_subtraction(slf, det, sciframe, modelvarframe, crmask, tracemask=trcmask)
        # Redetermine the variance frame based on the new sky model
        modelvarframe = variance_frame(slf, det, sciframe, scidx, fitsdict, skyframe=bgframe)
        # Save
        if not standard:
            slf._modelvarframe[det-1] = modelvarframe
            slf._bgframe[det-1] = bgframe

    ###############
    # Flexure down the slit? -- Not currently recommended
    if settings.argflag['reduce']['flexure']['method'] == 'slitcen':
        flex_dict = arwave.flexure_slit(slf, det)
        arqa.flexure(slf, det, flex_dict, slit_cen=True)

    ###############
    # Determine the final trace of the science objects
    msgs.info("Final trace")
    scitrace = artrace.trace_object(slf, det, sciframe-bgframe, modelvarframe, crmask, doqa=(not standard))
    if standard:
        slf._msstd[det-1]['trace'] = scitrace
        specobjs = arspecobj.init_exp(slf, scidx, det, fitsdict,
                                      trc_img=scitrace, objtype='standard')
        slf._msstd[det-1]['spobjs'] = specobjs
    else:
        slf._scitrace[det-1] = scitrace
        # Generate SpecObjExp list
        specobjs = arspecobj.init_exp(slf, scidx, det, fitsdict,
                                      trc_img=scitrace, objtype='science')
        slf._specobjs[det-1] = specobjs

    ###############
    # Extract
    if scitrace['nobj'] == 0:
        msgs.warn("No objects to extract for science frame"+msgs.newline()+fitsdict['filename'][scidx])
        return True

    # Boxcar
    msgs.info("Extracting")
    bgcorr_box = arextract.boxcar(slf, det, specobjs, sciframe-bgframe,
                                  rawvarframe, bgframe, crmask, scitrace)

    # Optimal
    if not standard:
        msgs.info("Attempting optimal extraction with model profile")
        arextract.obj_profiles(slf, det, specobjs, sciframe-bgframe-bgcorr_box,
                               modelvarframe, bgframe+bgcorr_box, crmask, scitrace)
        newvar = arextract.optimal_extract(slf, det, specobjs, sciframe-bgframe-bgcorr_box,
                                  modelvarframe, bgframe+bgcorr_box, crmask, scitrace)
        msgs.work("Should update variance image (and trace?) and repeat")
        #
        arextract.obj_profiles(slf, det, specobjs, sciframe-bgframe-bgcorr_box,
                               newvar, bgframe+bgcorr_box, crmask, scitrace)
        finalvar = arextract.optimal_extract(slf, det, specobjs, sciframe-bgframe-bgcorr_box,
                                           newvar, bgframe+bgcorr_box, crmask, scitrace)
        slf._modelvarframe[det-1] = finalvar.copy()

    # Flexure correction?
    if (settings.argflag['reduce']['flexure']['method'] is not None) and (not standard):
        flex_dict = arwave.flexure_obj(slf, det)
        arqa.flexure(slf, det, flex_dict)


    # Final
    if not standard:
        slf._bgframe[det-1] += bgcorr_box
    # Return
    return True


def sn_frame(slf, sciframe, idx):

    # Dark Current noise
    dnoise = settings.spect['det']['darkcurr'] * float(slf._fitsdict["exptime"][idx])/3600.0
    # The effective read noise
    rnoise = np.sqrt(settings.spect['det']['ronoise']**2 + (0.5*settings.spect['det']['gain'])**2)
    errframe = np.abs(sciframe) + rnoise + dnoise
    # If there are negative pixels, mask them as bad pixels
    w = np.where(errframe <= 0.0)
    if w[0].size != 0:
        msgs.warn("The error frame is negative for {0:d} pixels".format(w[0].size)+msgs.newline()+"Are you sure the bias frame is correct?")
        msgs.info("Masking these {0:d} pixels".format(w[0].size))
        errframe[w]  = 0.0
        slf._bpix[w] = 1.0
    w = np.where(errframe > 0.0)
    snframe = np.zeros_like(sciframe)
    snframe[w] = sciframe[w]/np.sqrt(errframe[w])
    return snframe


def lacosmic(slf, fitsdict, det, sciframe, scidx, maxiter=1, grow=1.5, maskval=-999999.9):
    """
    Identify cosmic rays using the L.A.Cosmic algorithm
    U{http://www.astro.yale.edu/dokkum/lacosmic/}
    (article : U{http://arxiv.org/abs/astro-ph/0108003})
    This routine is mostly courtesy of Malte Tewes

    :param grow: Once CRs are identified, grow each CR detection by all pixels within this radius
    :return: mask of cosmic rays (0=no CR, 1=CR)
    """
    from pypit import arcyutils
    from pypit import arcyproc
    dnum = settings.get_dnum(det)

    msgs.info("Detecting cosmic rays with the L.A.Cosmic algorithm")
    msgs.work("Include these parameters in the settings files to be adjusted by the user")
    sigclip = 5.0
    sigfrac = 0.3
    objlim  = 5.0
    # Set the settings
    scicopy = sciframe.copy()
    crmask = np.cast['bool'](np.zeros(sciframe.shape))
    sigcliplow = sigclip * sigfrac

    # Determine if there are saturated pixels
    satpix = np.zeros_like(sciframe)
    satlev = settings.spect[dnum]['saturation']*settings.spect[dnum]['nonlinear']
    wsat = np.where(sciframe >= satlev)
    if wsat[0].size == 0: satpix = None
    else:
        satpix[wsat] = 1.0
        satpix = np.cast['bool'](satpix)

    # Define the kernels
    laplkernel = np.array([[0.0, -1.0, 0.0], [-1.0, 4.0, -1.0], [0.0, -1.0, 0.0]])  # Laplacian kernal
    growkernel = np.ones((3,3))
    for i in range(1, maxiter+1):
        msgs.info("Convolving image with Laplacian kernel")
        # Subsample, convolve, clip negative values, and rebin to original size
        #set_trace()
        subsam = arutils.subsample(scicopy)
        conved = signal.convolve2d(subsam, laplkernel, mode="same", boundary="symm")
        cliped = conved.clip(min=0.0)
        lplus = arutils.rebin(cliped, np.array(cliped.shape)/2.0)

        msgs.info("Creating noise model")
        # Build a custom noise map, and compare  this to the laplacian
        m5 = ndimage.filters.median_filter(scicopy, size=5, mode='mirror')
        noise = np.sqrt(variance_frame(slf, det, m5, scidx, fitsdict))
        msgs.info("Calculating Laplacian signal to noise ratio")

        # Laplacian S/N
        s = lplus / (2.0 * noise)  # Note that the 2.0 is from the 2x2 subsampling

        # Remove the large structures
        sp = s - ndimage.filters.median_filter(s, size=5, mode='mirror')

        msgs.info("Selecting candidate cosmic rays")
        # Candidate cosmic rays (this will include HII regions)
        candidates = sp > sigclip
        nbcandidates = np.sum(candidates)

        msgs.info("{0:5d} candidate pixels".format(nbcandidates))

        # At this stage we use the saturated stars to mask the candidates, if available :
        if satpix is not None:
            msgs.info("Masking saturated pixels")
            candidates = np.logical_and(np.logical_not(satpix), candidates)
            nbcandidates = np.sum(candidates)

            msgs.info("{0:5d} candidate pixels not part of saturated stars".format(nbcandidates))

        msgs.info("Building fine structure image")

        # We build the fine structure image :
        m3 = ndimage.filters.median_filter(scicopy, size=3, mode='mirror')
        m37 = ndimage.filters.median_filter(m3, size=7, mode='mirror')
        f = m3 - m37
        f /= noise
        f = f.clip(min=0.01)

        msgs.info("Removing suspected compact bright objects")

        # Now we have our better selection of cosmics :
        cosmics = np.logical_and(candidates, sp/f > objlim)
        nbcosmics = np.sum(cosmics)

        msgs.info("{0:5d} remaining candidate pixels".format(nbcosmics))

        # What follows is a special treatment for neighbors, with more relaxed constains.

        msgs.info("Finding neighboring pixels affected by cosmic rays")

        # We grow these cosmics a first time to determine the immediate neighborhod  :
        growcosmics = np.cast['bool'](signal.convolve2d(np.cast['float32'](cosmics), growkernel, mode="same", boundary="symm"))

        # From this grown set, we keep those that have sp > sigmalim
        # so obviously not requiring sp/f > objlim, otherwise it would be pointless
        growcosmics = np.logical_and(sp > sigclip, growcosmics)

        # Now we repeat this procedure, but lower the detection limit to sigmalimlow :

        finalsel = np.cast['bool'](signal.convolve2d(np.cast['float32'](growcosmics), growkernel, mode="same", boundary="symm"))
        finalsel = np.logical_and(sp > sigcliplow, finalsel)

        # Unmask saturated pixels:
        if satpix != None:
            msgs.info("Masking saturated stars")
            finalsel = np.logical_and(np.logical_not(satpix), finalsel)

        ncrp = np.sum(finalsel)

        msgs.info("{0:5d} pixels detected as cosmics".format(ncrp))

        # We find how many cosmics are not yet known :
        newmask = np.logical_and(np.logical_not(crmask), finalsel)
        nnew = np.sum(newmask)

        # We update the mask with the cosmics we have found :
        crmask = np.logical_or(crmask, finalsel)

        msgs.info("Iteration {0:d} -- {1:d} pixels identified as cosmic rays ({2:d} new)".format(i, ncrp, nnew))
        if ncrp == 0: break
    # Additional algorithms (not traditionally implemented by LA cosmic) to remove some false positives.
    msgs.work("The following algorithm would be better on the rectified, tilts-corrected image")
    filt  = ndimage.sobel(sciframe, axis=1, mode='constant')
    filty = ndimage.sobel(filt/np.sqrt(np.abs(sciframe)), axis=0, mode='constant')
    filty[np.where(np.isnan(filty))]=0.0
    sigimg  = arcyproc.cr_screen(filty,0.0)
    sigsmth = ndimage.filters.gaussian_filter(sigimg,1.5)
    sigsmth[np.where(np.isnan(sigsmth))]=0.0
    sigmask = np.cast['bool'](np.zeros(sciframe.shape))
    sigmask[np.where(sigsmth>sigclip)] = True
    crmask = np.logical_and(crmask, sigmask)
    msgs.info("Growing cosmic ray mask by 1 pixel")
    crmask = arcyutils.grow_masked(crmask.astype(np.float), grow, 1.0)
    return crmask


def gain_frame(slf, det):
    """ Generate a gain image from the spect dict

    Parameters
    ----------
    slf
    det

    Returns
    -------
    gain_img : ndarray

    """
    dnum = settings.get_dnum(det)

    # Loop on amplifiers
    gain_img = np.zeros_like(slf._datasec[det-1])
    for ii in range(settings.spect[dnum]['numamplifiers']):
        amp = ii+1
        try:
            amppix = slf._datasec[det-1] == amp
            gain_img[amppix] = settings.spect[dnum]['gain'][amp - 1]
        except IndexError:
            debugger.set_trace()
    # Return
    return gain_img


def rn_frame(slf, det):
    """ Generate a RN image

    Parameters
    ----------
    slf
    det

    Returns
    -------
    rn_img : ndarray
      Read noise *variance* image (i.e. RN**2)
    """
    dnum = settings.get_dnum(det)

    # Loop on amplifiers
    rnimg = np.zeros_like(slf._datasec[det-1])
    for ii in range(settings.spect[dnum]['numamplifiers']):
        amp = ii+1
        amppix = slf._datasec[det-1] == amp
        rnimg[amppix] = (settings.spect[dnum]['ronoise'][ii]**2 +
                         (0.5*settings.spect[dnum]['gain'][ii])**2)
    # Return
    return rnimg


def sub_overscan(frame, det):
    """
    Subtract overscan

    Parameters
    ----------
    frame : ndarray
      frame which should have the overscan region subtracted
    det : int
      Detector Index

    Returns
    -------
    frame : ndarray
      The input frame with the overscan region subtracted
    """
    dnum = settings.get_dnum(det)

    for i in range(settings.spect[dnum]['numamplifiers']):
        # Determine the section of the chip that contains data
        datasec = "datasec{0:02d}".format(i+1)
        dx0, dx1 = settings.spect[dnum][datasec][0][0], settings.spect[dnum][datasec][0][1]
        dy0, dy1 = settings.spect[dnum][datasec][1][0], settings.spect[dnum][datasec][1][1]
        if dx0 < 0: dx0 += frame.shape[0]
        if dx1 <= 0: dx1 += frame.shape[0]
        if dy0 < 0: dy0 += frame.shape[1]
        if dy1 <= 0: dy1 += frame.shape[1]
        xds = np.arange(dx0, dx1)
        yds = np.arange(dy0, dy1)
        # Determine the section of the chip that contains the overscan region
        oscansec = "oscansec{0:02d}".format(i+1)
        ox0, ox1 = settings.spect[dnum][oscansec][0][0], settings.spect[dnum][oscansec][0][1]
        oy0, oy1 = settings.spect[dnum][oscansec][1][0], settings.spect[dnum][oscansec][1][1]
        if ox0 < 0: ox0 += frame.shape[0]
        if ox1 <= 0: ox1 += min(frame.shape[0], dx1)  # Truncate to datasec
        if oy0 < 0: oy0 += frame.shape[1]
        if oy1 <= 0: oy1 += min(frame.shape[1], dy1)  # Truncate to datasec
        xos = np.arange(ox0, ox1)
        yos = np.arange(oy0, oy1)
        w = np.ix_(xos, yos)
        oscan = frame[w]
        # Make sure the overscan section has at least one side consistent with datasec
        if dx1-dx0 == ox1-ox0:
            osfit = np.median(oscan, axis=1)  # Mean was hit by CRs
        elif dy1-dy0 == oy1-oy0:
            osfit = np.median(oscan, axis=0)
        elif settings.argflag['reduce']['overscan']['method'].lower() == "median":
            osfit = np.median(oscan)
        else:
            msgs.error("Overscan sections do not match amplifier sections for amplifier {0:d}".format(i+1))
        # Fit/Model the overscan region
        if settings.argflag['reduce']['overscan']['method'].lower() == "polynomial":
            c = np.polyfit(np.arange(osfit.size), osfit, settings.argflag['reduce']['overscan']['params'][0])
            ossub = np.polyval(c, np.arange(osfit.size))#.reshape(osfit.size,1)
        elif settings.argflag['reduce']['overscan']['method'].lower() == "savgol":
            ossub = savgol_filter(osfit, settings.argflag['reduce']['overscan']['params'][1], settings.argflag['reduce']['overscan']['params'][0])
        elif settings.argflag['reduce']['overscan']['method'].lower() == "median":  # One simple value
            ossub = osfit * np.ones(1)
        else:
            msgs.warn("Overscan subtraction method {0:s} is not implemented".format(settings.argflag['reduce']['overscan']['method']))
            msgs.info("Using a linear fit to the overscan region")
            c = np.polyfit(np.arange(osfit.size), osfit, 1)
            ossub = np.polyval(c, np.arange(osfit.size))#.reshape(osfit.size,1)
        # Determine the section of the chip that contains data for this amplifier
        wd = np.ix_(xds, yds)
        ossub = ossub.reshape(osfit.size, 1)
        if wd[0].shape[0] == ossub.shape[0]:
            frame[wd] -= ossub
        elif wd[1].shape[1] == ossub.shape[0]:
            frame[wd] -= ossub.T
        elif settings.argflag['reduce']['overscan']['method'].lower() == "median":
            frame[wd] -= osfit
        else:
            msgs.error("Could not subtract bias from overscan region --"+msgs.newline()+"size of extracted regions does not match")
    # Return
    del xds, yds, xos, yos, oscan
    return frame


def trim(frame, det):
    dnum = settings.get_dnum(det)
    for i in range(settings.spect[dnum]['numamplifiers']):
        datasec = "datasec{0:02d}".format(i+1)
        x0, x1 = settings.spect[dnum][datasec][0][0], settings.spect[dnum][datasec][0][1]
        y0, y1 = settings.spect[dnum][datasec][1][0], settings.spect[dnum][datasec][1][1]
        if x0 < 0:
            x0 += frame.shape[0]
        if x1 <= 0:
            x1 += frame.shape[0]
        if y0 < 0:
            y0 += frame.shape[1]
        if y1 <= 0:
            y1 += frame.shape[1]
        if i == 0:
            xv = np.arange(x0, x1)
            yv = np.arange(y0, y1)
        else:
            xv = np.unique(np.append(xv, np.arange(x0, x1)))
            yv = np.unique(np.append(yv, np.arange(y0, y1)))
    # Construct and array with the rows and columns to be extracted
    w = np.ix_(xv, yv)
#	if len(file.shape) == 2:
#		trimfile = file[w]
#	elif len(file.shape) == 3:
#		trimfile = np.zeros((w[0].shape[0],w[1].shape[1],file.shape[2]))
#		for f in range(file.shape[2]):
#			trimfile[:,:,f] = file[:,:,f][w]
#	else:
#		msgs.error("Cannot trim {0:d}D frame".format(int(len(file.shape))))
    try:
        return frame[w]
    except:
        msgs.bug("Odds are datasec is set wrong. Maybe due to transpose")
        debugger.set_trace()
        msgs.error("Cannot trim file")


def variance_frame(slf, det, sciframe, idx, fitsdict=None, skyframe=None, objframe=None):
    """ Calculate the variance image including detector noise
    Parameters
    ----------
    fitsdict : dict, optional
      Contains relevant information from fits header files
    objframe : ndarray, optional
      Model of object counts
    Returns
    -------
    variance image : ndarray
    """
    dnum = settings.get_dnum(det)

    # The effective read noise (variance image)
    rnoise = rn_frame(slf, det)
    if skyframe is not None:
        if objframe is None:
            objframe = np.zeros_like(skyframe)
        varframe = np.abs(skyframe + objframe - np.sqrt(2)*np.sqrt(rnoise)) + rnoise
        return varframe
    else:
        scicopy = sciframe.copy()
        # Dark Current noise
        dnoise = (settings.spect[dnum]['darkcurr'] *
                  float(fitsdict["exptime"][idx])/3600.0)
        # Return
        return np.abs(scicopy) + rnoise + dnoise
