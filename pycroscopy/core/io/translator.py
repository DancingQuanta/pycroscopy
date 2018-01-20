# -*- coding: utf-8 -*-
"""
Created on Tue Nov  3 15:07:16 2015

@author: Suhas Somnath
"""

from __future__ import division, print_function, absolute_import, unicode_literals

import abc
import time as tm
from os import path, remove

import numpy as np

from .io_utils import get_available_memory
from .microdata import MicroDataGroup, MicroDataset
from .hdf_utils import get_h5_obj_refs, link_h5_objects_as_attrs
from pycroscopy.core.io.io_hdf5 import ioHDF5  # Now the translator is responsible for writing the data.


class Translator(object):
    """
    Abstract class that defines the most basic functionality of a data format translator.
    A translator converts experimental data from binary / proprietary
    data formats to a single standardized HDF5 data file
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, max_mem_mb=1024):
        """
        Parameters
        -----------
        max_mem_mb : unsigned integer (Optional. Default = 1024)
            Maximum system memory (in megabytes) that the translator can use
            
        Returns
        -------
        Translator object
        """
        self.max_ram = min(max_mem_mb * 1024 ** 2, 0.75 * get_available_memory())

    @abc.abstractmethod
    def translate(self, filepath):
        """
        Abstract method.
        To be implemented by extensions of this class. God I miss Java!
        """
        pass

    @abc.abstractmethod
    def _parse_file_path(self, input_path):
        """
        Abstract method
        Parses the `input_path` to determine the `basename` and find
        the appropriate data files

        """
        pass

    @abc.abstractmethod
    def _read_data(self):
        """
        Abstract method
        Reads the data into the hdf5 datasets.
        """

    @staticmethod
    def simple_write(h5_path, data_name, translator_name, ds_main, aux_dset_list, parm_dict=None):
        """
        Writes the provided datasets and parameters to an h5 file
        
        Parameters
        ----------
        h5_path : String / Unicode
            Absolute path of the h5 file to be written
        data_name : String / Unicode
            Name of the data type
        translator_name : String / unicode
            Name of the translator
        ds_main : MicroDataset object
            Main dataset
        aux_dset_list : list of MicroDataset objects
            auxillary datasets to be written to the file
        parm_dict : dictionary (Optional)
            Dictionary of parameters

        Returns
        -------
        h5_path : String / unicode
            Absolute path of the written h5 file

        """
        if parm_dict is None:
            parm_dict = {}
        chan_grp = MicroDataGroup('Channel_000')
        chan_grp.add_children([ds_main])
        chan_grp.add_children(aux_dset_list)
        meas_grp = MicroDataGroup('Measurement_000')
        meas_grp.attrs = parm_dict
        meas_grp.add_children([chan_grp])
        spm_data = MicroDataGroup('')
        global_parms = generate_dummy_main_parms()
        global_parms['data_type'] = data_name
        global_parms['translator'] = translator_name
        spm_data.attrs = global_parms
        spm_data.add_children([meas_grp])

        aux_dset_names = list()
        for dset in aux_dset_list:
            if isinstance(dset, MicroDataset):
                aux_dset_names.append(dset.name)

        if path.exists(h5_path):
            remove(h5_path)

        hdf = ioHDF5(h5_path)
        h5_refs = hdf.writeData(spm_data, print_log=False)
        h5_raw = get_h5_obj_refs([ds_main.name], h5_refs)[0]
        link_h5_objects_as_attrs(h5_raw, get_h5_obj_refs(aux_dset_names, h5_refs))
        hdf.close()
        return h5_path


def generate_dummy_main_parms():
    """
    Generates a (dummy) dictionary of parameters that will be used at the root level of the h5 file

    Returns
    ----------
    main_parms : dictionary
        Dictionary containing basic descriptors that describe a dataset
    """
    main_parms = dict()
    main_parms['translate_date'] = tm.strftime("%Y_%m_%d")
    main_parms['instrument'] = 'cypher_west'
    main_parms['xcams_id'] = 'abc'
    main_parms['user_name'] = 'John Doe'
    main_parms['sample_name'] = 'PZT'
    main_parms['sample_description'] = 'Thin Film'
    main_parms['project_name'] = 'Band Excitation'
    main_parms['project_id'] = 'CNMS_2015B_X0000'
    main_parms['comments'] = 'Band Excitation data'
    main_parms['data_tool'] = 'be_analyzer'
    # This parameter actually need not be a dummy and can be extracted from the parms file
    main_parms['experiment_date'] = '2015-10-05 14:55:05'
    main_parms['experiment_unix_time'] = tm.time()
    # Need to fill in the x and y grid size here
    main_parms['grid_size_x'] = 1
    main_parms['grid_size_y'] = 1
    # Need to fill in the current X, Y, Z, Laser position here
    main_parms['current_position_x'] = 1
    main_parms['current_position_y'] = 1

    return main_parms


def make_position_mat(num_steps):
    """
    Sets the position index matrices and labels for each of the spatial dimensions.
    It is intentionally generic so that it works for any SPM dataset.

    Parameters
    ------------
    num_steps : List / numpy array
        Steps in each spatial direction.
        Note that the axes must be ordered from fastest varying to slowest varying

    Returns
    --------------
    pos_mat : 2D unsigned int numpy array
        arranged as [steps, spatial dimension]
    """

    num_steps = np.array(num_steps)
    spat_dims = max(1, len(np.where(num_steps > 1)[0]))

    pos_mat = np.zeros(shape=(np.prod(num_steps), spat_dims), dtype=np.uint32)
    pos_ind = 0

    for indx, curr_steps in enumerate(num_steps):
        if curr_steps > 1:

            part1 = np.prod(num_steps[:indx+1])

            if indx > 0:
                part2 = np.prod(num_steps[:indx])
            else:
                part2 = 1

            if indx+1 == len(num_steps):
                part3 = 1
            else:
                part3 = np.prod(num_steps[indx+1:])

            pos_mat[:, pos_ind] = np.tile(np.floor(np.arange(part1)/part2), part3)
            pos_ind += 1

    return pos_mat


def get_position_slicing(pos_lab, curr_pix=None):
    """
    Returns a dictionary of slice objects to help in creating region references
    to the position indices and values H5 datasets

    Parameters
    ------------
    pos_lab : List of strings
        Labels of each of the position axes
    curr_pix : (Optional) unsigned int
        Last pixel in the positon matrix. Useful in experiments where the
        parameters have changed (eg. BEPS new data format)

    Returns
    ------------
    slice_dict : dictionary
        Dictionary of tuples containing slice objects corresponding to
        each position axis.
    """
    slice_dict = dict()
    for spat_ind, spat_dim in enumerate(pos_lab):
        slice_dict[spat_dim] = (slice(curr_pix), slice(spat_ind, spat_ind+1))
    return slice_dict


def get_spectral_slicing(spec_lab, curr_spec=None):
    """
    Returns a dictionary of slice objects to help in creating region references
    to the spectroscopic indices and values H5 datasets

    Parameters
    ------------
    spec_lab : List of strings
        Labels of each of the Spectroscopic axes
    curr_spec : (Optional) unsigned int
        Last position in the spectroscopic matrix. Useful in experiments where the
        parameters have changed (eg. BEPS new data format)

    Returns
    ------------
    slice_dict : dictionary
        Dictionary of tuples containing slice objects corresponding to
        each Spectroscopic axis.
    """
    slice_dict = dict()
    for spat_ind, spat_dim in enumerate(spec_lab):
        slice_dict[spat_dim] = (slice(spat_ind, spat_ind + 1), slice(curr_spec))
    return slice_dict


def build_ind_val_dsets(dimensions, is_spectral=True, steps=None, initial_values=None, labels=None,
                        units=None, verbose=False):
    """
    Builds the MicroDatasets for the position OR spectroscopic indices and values
    of the data

    Parameters
    ----------
    is_spectral : Boolean
        Spectroscopic (True) or Position (False)
    dimensions : array_like of numpy.uint
        Integer values for the length of each dimension
    steps : array_like of float, optional
        Floating point values for the step-size in each dimension.  One
        if not specified.
    initial_values : array_like of float, optional
        Floating point for the zeroth value in each dimension.  Zero if
        not specified.
    labels : array_like of str, optional
        The names of each dimension.  Empty strings will be used if not
        specified.
    units : array_like of str, optional
        The units of each dimension.  Empty strings will be used if not
        specified.
    verbose : Boolean, optional
        Whether or not to print statements for debugging purposes

    Returns
    -------
    ds_spec_inds : Microdataset of numpy.uint
        Dataset containing the position indices
    ds_spec_vals : Microdataset of float
        Dataset containing the value at each position

    Notes
    -----
    `steps`, `initial_values`, `labels`, and 'units' must be the same length as
    `dimensions` when they are specified.

    Dimensions should be in the order from fastest varying to slowest.
    """

    if steps is None:
        steps = np.ones_like(dimensions)
    elif len(steps) != len(dimensions):
        raise ValueError('The arrays for step sizes and dimension sizes must be the same.')
    steps = np.atleast_2d(steps)
    if verbose:
        print('Steps')
        print(steps.shape)
        print(steps)

    if initial_values is None:
        initial_values = np.zeros_like(dimensions)
    elif len(initial_values) != len(dimensions):
        raise ValueError('The arrays for initial values and dimension sizes must be the same.')
    initial_values = np.atleast_2d(initial_values)

    if verbose:
        print('Initial Values')
        print(initial_values.shape)
        print(initial_values)

    if labels is None:
        labels = ['' for _ in dimensions]
    elif len(labels) != len(dimensions):
        raise ValueError('The arrays for labels and dimension sizes must be the same.')

    # Get the indices for all dimensions
    indices = make_position_mat(dimensions)
    if verbose:
        print('Indices')
        print(indices.shape)
        print(indices)

    # Convert the indices to values
    values = initial_values + np.float32(indices)*steps

    # Create the slices that will define the labels
    if is_spectral:
        mode = 'Spectroscopic_'
        indices = indices.transpose()
        values = values.transpose()
        region_slices = get_spectral_slicing(labels)
    else:
        mode = 'Position_'
        region_slices = get_position_slicing(labels)

    # Create the MicroDatasets for both Indices and Values
    ds_indices = MicroDataset(mode + 'Indices', indices, dtype=np.uint32)
    ds_indices.attrs['labels'] = region_slices

    ds_values = MicroDataset(mode + 'Values', np.float32(values), dtype=np.float32)
    ds_values.attrs['labels'] = region_slices

    if units is None:
        pass
    elif len(units) != len(dimensions):
        raise ValueError('The arrays for labels and dimension sizes must be the same.')
    else:
        ds_indices.attrs['units'] = units
        ds_values.attrs['units'] = units

    return ds_indices, ds_values