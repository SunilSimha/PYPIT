from __future__ import (print_function, absolute_import, division, unicode_literals)

import sys
import os
import numpy as np
import yaml

from collections import OrderedDict

from pypit import arparse as settings
from pypit import armsgs
from pypit import arsort
from pypit import arsciexp
from pypit import arutils

# Logging
msgs = armsgs.get_logger()

from pypit import ardebug as debugger


def SetupScience(fitsdict):
    """ Create an exposure class for every science frame
    Also links to standard star frames and calibrations
    Also search for slitless twilight flats

    Parameters
    ----------
    fitsdict : dict
      Contains relevant information from fits header files

    Returns
    -------
    sciexp : list
      A list containing all science exposure classes
    """
    # Init
    if settings.argflag['run']['calcheck'] or settings.argflag['run']['setup']:
        do_qa = False
        bad_to_unknown = True
    else:
        do_qa = True
        bad_to_unknown = False
    if settings.argflag['run']['setup']:
        skip_cset = True
    else:
        skip_cset = False
    # Sort the data
    msgs.bug("Files and folders should not be deleted -- there should be an option to overwrite files automatically if they already exist, or choose to rename them if necessary")
    filesort = arsort.sort_data(fitsdict, flag_unknown=bad_to_unknown)
    # Write out the details of the sorted files
    if settings.argflag['output']['sorted'] is not None:
        srt_tbl = arsort.sort_write(fitsdict, filesort)
    # Match calibration frames to science frames
    arsort.match_science(fitsdict, filesort)
    # Make directory structure for different objects
    if do_qa:
        sci_targs = arsort.make_dirs(fitsdict, filesort)
    # Create the list of science exposures
    numsci = np.size(filesort['science'])
    sciexp = []
    for i in range(numsci):
        sciexp.append(arsciexp.ScienceExposure(i, fitsdict, do_qa=do_qa))
    # Generate setup and group dicts
    setup_dict = {}
    # Run through the setups to fill setup_dict
    setupIDs = []
    for sc in range(numsci):
        for kk in range(settings.spect['mosaic']['ndet']):
            setupID = arsort.instr_setup(sciexp[sc]._idx_arcs[0], kk+1, fitsdict, setup_dict, skip_cset=skip_cset, sciexp=sciexp[sc])
            if kk == 0:  # Only save the first detector for run setup
                setupIDs.append(setupID)
    # Slitless flats?
    #arsort.scan_for_slitless(fitsdict, filesort)
    sless_IDs = []
    for sidx in filesort['slitless']:
        slessID = arsort.instr_setup(sidx, 1, fitsdict, setup_dict, skip_cset=True)
        sless_IDs.append(slessID)
    # Group
    group_dict = {}
    if settings.argflag['run']['setup']: # Collate all matching files
        # Loop on science frames
        for sc,setupID in enumerate(setupIDs):
            scidx = sciexp[sc]._idx_sci[0]
            # Set group_key
            config_key = setupID[0]
            # Plan init
            if config_key not in group_dict.keys():
                group_dict[config_key] = {}
                for key in filesort.keys():
                    if key not in ['unknown', 'dark']:
                        group_dict[config_key][key] = []
                    group_dict[config_key]['sciobj'] = []
                    group_dict[config_key]['stdobj'] = []
            # Fill group_dict too
            for key in filesort.keys():
                if key in ['unknown', 'dark']:
                    continue
                for idx in settings.spect[key]['index'][sc]:
                    # Only add if new
                    if fitsdict['filename'][idx] not in group_dict[config_key][key]:
                        group_dict[config_key][key].append(fitsdict['filename'][idx])
                        if key == 'standard':  # Add target name
                            group_dict[config_key]['stdobj'].append(fitsdict['target'][idx])
                    if key == 'science':  # Add target name
                        group_dict[config_key]['sciobj'].append(fitsdict['target'][scidx])
        # Loop on slitless frames -- Separate setups
        for slessID in sless_IDs:
            config_key = slessID[0]
            if config_key not in group_dict.keys():
                group_dict[config_key] = {}
                mti = np.array(sless_IDs) == slessID
                sidx = filesort['slitless'][mti]
                group_dict[config_key]['slitless'] = fitsdict['filename'][sidx].tolist()
        # Write .sorted file
        arsort.write_sorted(srt_tbl, group_dict, setup_dict)

    # Write setup -- only if not present
    setup_file, nexist = arsort.get_setup_file()
    arsort.write_setup(setup_dict)
    # Write calib file (if not in setup mode)
    if not settings.argflag['run']['setup']:
        arsort.write_calib(setup_dict)
    # Finish calcheck or setup
    if settings.argflag['run']['calcheck'] or settings.argflag['run']['setup']:
        if settings.argflag['run']['calcheck']:
            msgs.info("Inspect the .calib file: {:s}".format(setup_file))
            msgs.info("Calibration check complete. Set 'run calcheck False' to continue with data reduction")
            return 'calcheck', None
        elif settings.argflag['run']['setup']:
            msgs.info("Setup is complete. Change 'run setup' to False to continue with data reduction")
            msgs.info("Inspect the .setups file: {:s}".format(setup_file))
            return 'setup', None
        else:
            msgs.error("Should not get here")
    return sciexp, setup_dict


def UpdateMasters(sciexp, sc, det, ftype=None, chktype=None):
    """ Update the master calibrations for other science targets

    If they will use an identical master frame

    Parameters
    ----------
    sciexp : list
      A list containing all science exposure classes
    sc : int
      Index of sciexp for the science exposure currently being reduced
    det : int
      detector index (starting from 1)
    ftype : str
      Describes the type of Master frame being udpated
    chktype : str
      Describes the subtype of Master frame being updated
    """
    numsci = len(sciexp)
    if ftype == "arc":
        chkarr = sciexp[sc]._idx_arcs
    elif ftype == "bias": chkarr = sciexp[sc]._idx_bias
    elif ftype == "readnoise": chkarr = sciexp[sc]._idx_rn
    elif ftype == "flat":
        if chktype == "trace": chkarr = sciexp[sc]._idx_trace
        elif chktype == "pixelflat": chkarr = sciexp[sc]._idx_flat
        elif chktype == "pinhole": chkarr = sciexp[sc]._idx_cent
        else:
            msgs.bug("I could not update frame of type {0:s} and subtype {1:s}".format(ftype, chktype))
            return
    elif ftype == "standard": chkarr = sciexp[sc]._idx_std
    else:
        msgs.bug("I could not update frame of type: {0:s}".format(ftype))
        return
    if ftype == "flat":
        # First check flats of the same type
        for i in range(sc+1, numsci):
            # Check if an *identical* master frame has already been produced
            if chktype == "trace": chkfarr = sciexp[i]._idx_trace
            elif chktype == "pixelflat": chkfarr = sciexp[i]._idx_flat
            elif chktype == "pinhole": chkfarr = sciexp[i]._idx_cent
            else:
                msgs.bug("I could not update frame of type {0:s} and subtype {1:s}".format(ftype, chktype))
                return
            if np.array_equal(chkarr, chkfarr) and sciexp[i].GetMasterFrame(chktype, det, mkcopy=False) is None:
                msgs.info("Updating master {0:s} frame for science target {1:d}/{2:d}".format(chktype, i+1, numsci))
                sciexp[i].SetMasterFrame(sciexp[sc].GetMasterFrame(chktype, det), chktype, det)
        # Now check flats of a different type
        origtype = chktype
        if chktype == "trace": chktype = "pixelflat"
        elif chktype == "pixelflat": chktype = "trace"
        for i in range(sc, numsci):
            # Check if an *identical* master frame has already been produced
            if chktype == "trace": chkfarr = sciexp[i]._idx_trace
            elif chktype == "pixelflat": chkfarr = sciexp[i]._idx_flat
            elif chktype == "pinhole": chkfarr = sciexp[i]._idx_cent
            else:
                msgs.bug("I could not update frame of type {0:s} and subtype {1:s}".format(ftype, chktype))
                return
            if np.array_equal(chkarr, chkfarr) and sciexp[i].GetMasterFrame(chktype, det, mkcopy=False) is None:
                msgs.info("Updating master {0:s} frame for science target {1:d}/{2:d}".format(chktype, i+1, numsci))
                sciexp[i].SetMasterFrame(sciexp[sc].GetMasterFrame(origtype, det), chktype, det)
    else:
        for i in range(sc+1, numsci):
            # Check if an *identical* master frame has already been produced
            if ftype == "arc":
                chkfarr = sciexp[i]._idx_arcs
            elif ftype == "bias": chkfarr = sciexp[i]._idx_bias
            elif ftype == "standard": chkfarr = sciexp[i]._idx_std
            else:
                msgs.bug("I could not update frame of type: {0:s}".format(ftype))
                return
            if np.array_equal(chkarr, chkfarr) and sciexp[i].GetMasterFrame(ftype, det, mkcopy=False) is None:
                msgs.info("Updating master {0:s} frame for science target {1:d}/{2:d}".format(ftype, i+1, numsci))
                sciexp[i].SetMasterFrame(sciexp[sc].GetMasterFrame(ftype, det), ftype, det)
    return

