"""Thin HDF5 save/load helpers, replacing the (now dropped) ``flammkuchen``
dependency.

stytra's actual usage of flammkuchen was narrow - a plain ndarray, or one
flat dict of ndarrays with optional blosc compression - so rather than
vendor flammkuchen's general-purpose (sparse matrices, pickling fallback,
arbitrary nesting) serializer, this wraps ``tables`` (PyTables, the package
flammkuchen itself sits on top of, and already a stytra dependency) directly
for just those two shapes.
"""

import numpy as np
import tables


def save_h5_array(path, array, compression=None):
    """Save a single ndarray as the sole content of an HDF5 file."""
    filters = (
        tables.Filters(complib=compression, complevel=5, shuffle=True)
        if compression
        else None
    )
    with tables.open_file(str(path), mode="w") as f:
        if filters is not None:
            f.create_carray(f.root, "array", obj=np.asarray(array), filters=filters)
        else:
            f.create_array(f.root, "array", obj=np.asarray(array))


def save_h5_dict(path, data, compression=None):
    """Save a flat dict of ndarray-like values to an HDF5 file."""
    filters = (
        tables.Filters(complib=compression, complevel=5, shuffle=True)
        if compression
        else None
    )
    with tables.open_file(str(path), mode="w") as f:
        for key, value in data.items():
            value = np.asarray(value)
            if filters is not None:
                f.create_carray(f.root, key, obj=value, filters=filters)
            else:
                f.create_array(f.root, key, obj=value)


def load_h5(path):
    """Load an HDF5 file written by ``save_h5_array``/``save_h5_dict``.

    Returns a plain ndarray if the file holds exactly one top-level array
    (the ``save_h5_array`` case), otherwise a dict of arrays keyed by name.
    """
    with tables.open_file(str(path), mode="r") as f:
        arrays = {node.name: node.read() for node in f.root._f_iter_nodes()}
    if list(arrays.keys()) == ["array"]:
        return arrays["array"]
    return arrays
