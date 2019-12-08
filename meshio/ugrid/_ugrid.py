"""
I/O for AFLR's UGRID format
[1] <http://www.simcenter.msstate.edu/software/downloads/doc/ug_io/3d_grid_file_type_ugrid.html>.
Check out
[2] <http://www.simcenter.msstate.edu/software/downloads/ug_io/index_simsys_web.php?path=release>
for UG_IO C code able to read and convert UGRID files
Node ordering described in
[3] http://www.simcenter.msstate.edu/software/downloads/doc/ug_io/3d_input_output_grids.html
"""
import logging

import numpy

from .._exceptions import ReadError
from .._files import open_file
from .._helpers import register
from .._mesh import Mesh

# Float size and endianess are recorded by these suffixes
# binary files come in C-type or FORTRAN type
# http://www.simcenter.msstate.edu/software/downloads/doc/ug_io/ugc_file_formats.html
#
# 64-bit versions described here
# http://www.simcenter.msstate.edu/software/downloads/doc/ug_io/ugc_l_file_formats.html
file_types = {
    "ascii": {"type": "ascii", "float_type": "f", "int_type": "i"},
    "b8l": {"type": "C", "float_type": ">f8", "int_type": ">i8"},
    "b8": {"type": "C", "float_type": ">f8", "int_type": ">i4"},
    "b4": {"type": "C", "float_type": ">f4", "int_type": ">i4"},
    "lb8l": {"type": "C", "float_type": "<f8", "int_type": "<i8"},
    "lb8": {"type": "C", "float_type": "<f8", "int_type": "<i4"},
    "lb4": {"type": "C", "float_type": "<f4", "int_type": "<i4"},
    "r8": {"type": "F", "float_type": ">f8", "int_type": ">i4"},
    "r4": {"type": "F", "float_type": ">f4", "int_type": ">i4"},
    "lr8": {"type": "F", "float_type": "<f8", "int_type": "<i4"},
    "lr4": {"type": "F", "float_type": "<f4", "int_type": "<i4"},
}

file_type = None


def determine_file_type(filename):
    file_type = file_types["ascii"]
    filename_parts = filename.split(".")
    if len(filename_parts) > 1:
        type_suffix = filename_parts[-2]
        if type_suffix in file_types.keys():
            file_type = file_types[type_suffix]

    return file_type


def read(filename):

    global file_type

    file_type = determine_file_type(filename)

    with open_file(filename) as f:
        mesh = read_buffer(f)
    return mesh


def read_buffer(f):
    cells = {}
    cell_data = {}

    itype = file_type["int_type"]
    ftype = file_type["float_type"]

    def read_section(count, dtype):
        if file_type["type"] == "ascii":
            return numpy.fromfile(f, count=count, dtype=dtype, sep=" ")
        else:
            return numpy.fromfile(f, count=count, dtype=dtype)

    # FORTRAN type includes a number of bytes before and after
    # each record , according to documentation [1] there are
    # two records in the file
    # see also UG_IO freely available code at [2]
    if file_type["type"] == "F":
        numpy.fromfile(f, count=1, dtype=itype)

    nitems = read_section(count=7, dtype=itype)

    if file_type["type"] == "F":
        numpy.fromfile(f, count=1, dtype=itype)

    if not nitems.size == 7:
        raise ReadError("Header of ugrid file is ill-formed")

    ugrid_counts = {
        "points": (nitems[0], 3),
        "triangle": (nitems[1], 3),
        "quad": (nitems[2], 4),
        "tetra": (nitems[3], 4),
        "pyramid": (nitems[4], 5),
        "wedge": (nitems[5], 6),
        "hexahedron": (nitems[6], 8),
    }

    if file_type["type"] == "F":
        numpy.fromfile(f, count=1, dtype=itype)

    nnodes = ugrid_counts["points"][0]
    points = read_section(count=nnodes * 3, dtype=ftype).reshape(nnodes, 3)

    for key in ["triangle", "quad"]:
        nitems = ugrid_counts[key][0]
        nvertices = ugrid_counts[key][1]
        if nitems == 0:
            continue
        out = read_section(count=nitems * nvertices, dtype=itype).reshape(
            nitems, nvertices
        )
        # UGRID is one-based
        cells[key] = out - 1

    for key in ["triangle", "quad"]:
        nitems = ugrid_counts[key][0]
        if nitems == 0:
            continue
        out = read_section(count=nitems, dtype=itype)
        cell_data[key] = {"ugrid:ref": out}

    for key in ["tetra", "pyramid", "wedge", "hexahedron"]:
        nitems = ugrid_counts[key][0]
        nvertices = ugrid_counts[key][1]
        if nitems == 0:
            continue
        out = read_section(count=nitems * nvertices, dtype=itype).reshape(
            nitems, nvertices
        )

        if key == "pyramid":
            out = out[:, [1, 0, 4, 2, 3]]

        # UGRID is one-based
        cells[key] = out - 1

        # fill volume element attributes with zero
        out = numpy.zeros(nitems)
        cell_data[key] = {"ugrid:ref": out}

    if file_type["type"] == "F":
        numpy.fromfile(f, count=1, dtype=itype)

    return Mesh(points, cells, cell_data=cell_data)


def write(filename, mesh):
    file_type = determine_file_type(filename)

    with open_file(filename, "w") as f:
        itype = file_type["int_type"]
        ftype = file_type["float_type"]

        def write_section(array, dtype):
            if file_type["type"] == "ascii":
                fmt = " ".join(["%{}".format(dtype)] * (array.shape[1]))
                numpy.savetxt(f, array, fmt)
            else:
                array.astype(dtype).tofile(f)

        ugrid_counts = {
            "points": 0,
            "triangle": 0,
            "quad": 0,
            "tetra": 0,
            "pyramid": 0,
            "wedge": 0,
            "hexahedron": 0,
        }

        ugrid_counts["points"] = mesh.points.shape[0]

        for key, data in mesh.cells.items():
            if key in ugrid_counts.keys():
                ugrid_counts[key] = data.shape[0]
            else:
                msg = ("UGRID mesh format doesn't know {} cells. Skipping.").format(key)
                logging.warning(msg)
                continue

        nitems = numpy.array(
            [
                [
                    ugrid_counts["points"],
                    ugrid_counts["triangle"],
                    ugrid_counts["quad"],
                    ugrid_counts["tetra"],
                    ugrid_counts["pyramid"],
                    ugrid_counts["wedge"],
                    ugrid_counts["hexahedron"],
                ]
            ]
        )
        # header
        write_section(nitems, itype)
        write_section(mesh.points, ftype)

        for key in ["triangle", "quad"]:
            if ugrid_counts[key] > 0:
                # UGRID is one-based
                out = mesh.cells[key] + 1
                write_section(out, itype)

        # write boundary tags
        for key in ["triangle", "quad"]:
            if ugrid_counts[key] == 0:
                continue
            if "ugrid:ref" in mesh.cell_data[key]:
                labels = mesh.cell_data[key]["ugrid:ref"]
            elif "medit:ref" in mesh.cell_data[key]:
                labels = mesh.cell_data[key]["medit:ref"]
            elif "gmsh:physical" in mesh.cell_data[key]:
                labels = mesh.cell_data[key]["gmsh:physical"]
            elif key in mesh.cell_data and "flac3d:zone" in mesh.cell_data[key]:
                labels = mesh.cell_data[key]["flac3d:zone"]
            else:
                labels = numpy.ones(ugrid_counts[key], dtype=itype)

            labels = labels.reshape(ugrid_counts[key], 1)
            write_section(labels, itype)

        # write volume elements
        for key in ["tetra", "pyramid", "wedge", "hexahedron"]:
            if ugrid_counts[key] == 0:
                continue
            # UGRID is one-based
            out = mesh.cells[key] + 1
            if key == "pyramid":
                out = out[:, [1, 0, 4, 2, 3]]
            write_section(out, itype)
    return


register("ugrid", [".ugrid"], read, {"ugrid": write})
