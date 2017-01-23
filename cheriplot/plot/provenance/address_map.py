#-
# Copyright (c) 2016 Alfredo Mazzinghi
# All rights reserved.
#
# This software was developed by SRI International and the University of
# Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-10-C-0237
# ("CTSRD"), as part of the DARPA CRASH research programme.
#
# @BERI_LICENSE_HEADER_START@
#
# Licensed to BERI Open Systems C.I.C. (BERI) under one or more contributor
# license agreements.  See the NOTICE file distributed with this work for
# additional information regarding copyright ownership.  BERI licenses this
# file to you under the BERI Hardware-Software License, Version 1.0 (the
# "License"); you may not use this file except in compliance with the
# License.  You may obtain a copy of the License at:
#
#   http://www.beri-open-systems.org/legal/license-1-0.txt
#
# Unless required by applicable law or agreed to in writing, Work distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations under the License.
#
# @BERI_LICENSE_HEADER_END@
#

import numpy as np
import logging

from matplotlib import pyplot as plt
from matplotlib import collections, transforms, patches, text
from matplotlib.colors import colorConverter

from cheriplot.utils import ProgressPrinter
from cheriplot.core.addrspace_axes import Range
from cheriplot.core.vmmap import VMMap
from cheriplot.core.provenance import CheriCapPerm, CheriNodeOrigin
from cheriplot.plot.patch import PatchBuilder, OmitRangeSetBuilder
from cheriplot.plot.provenance.provenance_plot import PointerProvenancePlot

logger = logging.getLogger(__name__)

class ColorCodePatchBuilder(PatchBuilder):
    """
    The patch generator build the matplotlib patches for each
    capability node.

    The nodes are rendered as lines with a different color depending
    on the permission bits of the capability. The builder produces
    a LineCollection for each combination of permission bits and
    creates the lines for the nodes.
    """

    def __init__(self):
        super(ColorCodePatchBuilder, self).__init__()

        self.y_unit = 10**-6
        """Unit on the y-axis"""

        self._omit_collection = np.empty((1,2,2))
        """Collection of elements in omit ranges"""

        self._keep_collection = np.empty((1,2,2))
        """Collection of elements in keep ranges"""

        # permission composition shorthands
        load_store = CheriCapPerm.LOAD | CheriCapPerm.STORE
        load_exec = CheriCapPerm.LOAD | CheriCapPerm.EXEC
        store_exec = CheriCapPerm.STORE | CheriCapPerm.EXEC
        load_store_exec = (CheriCapPerm.STORE |
                           CheriCapPerm.LOAD |
                           CheriCapPerm.EXEC)

        self._collection_map = {
            0: [],
            CheriCapPerm.LOAD: [],
            CheriCapPerm.STORE: [],
            CheriCapPerm.EXEC: [],
            load_store: [],
            load_exec: [],
            store_exec: [],
            load_store_exec: [],
            "call": [],
        }
        """Map capability permission to the set where the line should go"""

        self._colors = {
            0: colorConverter.to_rgb("#bcbcbc"),
            CheriCapPerm.LOAD: colorConverter.to_rgb("k"),
            CheriCapPerm.STORE: colorConverter.to_rgb("y"),
            CheriCapPerm.EXEC: colorConverter.to_rgb("m"),
            load_store: colorConverter.to_rgb("c"),
            load_exec: colorConverter.to_rgb("b"),
            store_exec: colorConverter.to_rgb("g"),
            load_store_exec: colorConverter.to_rgb("r"),
            "call": colorConverter.to_rgb("#31c648"),
        }
        """Map capability permission to line colors"""

        self._patches = None
        """List of enerated patches"""

        self._arrow_collection = []
        """Collection of arrow coordinates"""

    def _build_patch(self, node_range, y, perms):
        """
        Build patch for the given range and type and add it
        to the patch collection for drawing
        """
        line = [(node_range.start, y), (node_range.end, y)]

        if perms is None:
            perms = 0
        rwx_perm = perms & (CheriCapPerm.LOAD |
                            CheriCapPerm.STORE |
                            CheriCapPerm.EXEC)
        self._collection_map[rwx_perm].append(line)

    def _build_call_patch(self, node_range, y, origin):
        """
        Build patch for a node representing a system call
        This is added to a different collection so it can be
        colored differently.
        """
        line = [(node_range.start, y), (node_range.end, y)]
        self._collection_map["call"].append(line)

    def inspect(self, node):
        if node.cap.bound < node.cap.base:
            logger.warning("Skip overflowed node %s", node)
            return
        node_y = node.cap.t_alloc * self.y_unit
        node_box = transforms.Bbox.from_extents(node.cap.base, node_y,
                                                node.cap.bound, node_y)

        self._bbox = transforms.Bbox.union([self._bbox, node_box])
        keep_range = Range(node.cap.base, node.cap.bound, Range.T_KEEP)
        if node.origin == CheriNodeOrigin.SYS_MMAP:
            self._build_call_patch(keep_range, node_y, node.origin)
        else:
            self._build_patch(keep_range, node_y, node.cap.permissions)

        #invalidate collections
        self._patches = None
        # # build arrows
        # for child in node:
        #     self._build_provenance_arrow(node, child)

    def get_patches(self):
        if self._patches:
            return self._patches
        self._patches = []
        for key, collection in self._collection_map.items():
            coll = collections.LineCollection(collection,
                                              colors=[self._colors[key]],
                                              linestyle="solid")
            self._patches.append(coll)
        return self._patches

    def get_legend(self):
        if not self._patches:
            self.get_patches()
        legend = ([], [])
        for patch, key in zip(self._patches, self._collection_map.keys()):
            legend[0].append(patch)
            if key == "call":
                legend[1].append("mmap")
            else:
                perm_string = ""
                if key & CheriCapPerm.LOAD:
                    perm_string += "R"
                if key & CheriCapPerm.STORE:
                    perm_string += "W"
                if key & CheriCapPerm.EXEC:
                    perm_string += "X"
                if perm_string == "":
                    perm_string = "None"
                legend[1].append(perm_string)
        return legend


class VMMapPatchBuilder(PatchBuilder):
    """
    Build the patches that highlight the vmmap boundaries in the
    AddressMapPlot
    """

    def __init__(self):
        super(VMMapPatchBuilder, self).__init__()

        self.y_max = np.inf
        """Max value on the y-axis computed by the AddressMapPlot"""

        self.patches = []
        """List of rectangles"""

        self.patch_colors = []
        """List of colors for the patches"""

        self.annotations = []
        """Text labels"""

        self._colors = {
            "": colorConverter.to_rgb("#bcbcbc"),
            "r": colorConverter.to_rgb("k"),
            "w": colorConverter.to_rgb("y"),
            "x": colorConverter.to_rgb("m"),
            "rw": colorConverter.to_rgb("c"),
            "rx": colorConverter.to_rgb("b"),
            "wx": colorConverter.to_rgb("g"),
            "rwx": colorConverter.to_rgb("r")
        }
        """Map section permission to line colors"""

    def inspect(self, vmentry):
        rect = patches.Rectangle((vmentry.start, 0),
                                 vmentry.end - vmentry.start, self.y_max)
        self.patches.append(rect)
        self.patch_colors.append(self._colors[vmentry.perms])

        label_position = ((vmentry.start + vmentry.end) / 2, self.y_max / 2)
        vme_path = str(vmentry.path).split("/")[-1] if str(vmentry.path) else ""
        if not vme_path and vmentry.grows_down:
            vme_path = "stack"
        vme_label = "%s %s" % (vmentry.perms, vme_path)
        label = text.Text(text=vme_label, rotation="vertical",
                          position=label_position,
                          horizontalalignment="center",
                          verticalalignment="center")
        self.annotations.append(label)


    def params(self, **kwargs):
        self.y_max = kwargs.get("y_max", self.y_max)

    def get_patches(self):
        coll = collections.PatchCollection(self.patches, alpha=0.1,
                                           facecolors=self.patch_colors)
        return [coll]

    def get_annotations(self):
        return self.annotations


class AddressMapOmitBuilder(OmitRangeSetBuilder):
    """
    The omit builder generates the ranges of address-space in
    which we are not interested.

    Generate address ranges that are displayed as shortened in the
    address-space plot based on the size of each capability.
    If the allocations are spaced out more than a given number of pages,
    the space in between is "omitted" in the plot, if no other
    capability should be rendered into such range. The effect is to
    shrink portions of the address-space where there are no interesting
    features.
    """

    def __init__(self):
        super(AddressMapOmitBuilder, self).__init__()

        self.split_size = 2 * self.size_limit
        """
        Capability length threshold to trigger the omission of
        the middle portion of the capability range.
        """

    def inspect(self, node):
        if node.cap.bound < node.cap.base:
            logger.warning("Skip overflowed node %s", node)
            return
        keep_range = Range(node.cap.base, node.cap.bound, Range.T_KEEP)
        self.inspect_range(keep_range)

    def inspect_range(self, node_range):
        if node_range.size > self.split_size:
            l_range = Range(node_range.start,
                            node_range.start + self.size_limit,
                            Range.T_KEEP)
            r_range = Range(node_range.end - self.size_limit,
                            node_range.end,
                            Range.T_KEEP)
            self._update_regions(l_range)
            self._update_regions(r_range)
        else:
            self._update_regions(node_range)


class AddressMapPlot(PointerProvenancePlot):
    """
    Plot the provenance tree showing the time of allocation vs
    base and bound of each node.
    """

    def __init__(self, *args, **kwargs):
        super(AddressMapPlot, self).__init__(*args, **kwargs)

        self.patch_builder = ColorCodePatchBuilder()
        """
        Helper object that builds the plot components.
        See :class:`.ColorCodePatchBuilder`
        """

        self.range_builder = AddressMapOmitBuilder()
        """
        Helper objects that detects the interesting
        parts of the address-space.
        See :class:`.AddressMapOmitBuilder`
        """

        self.vmmap_patch_builder = VMMapPatchBuilder()
        """
        Helper object that builds patches to display VM map regions.
        See :class:`.VMMapPatchBuilder`
        """

        self.vmmap = None
        """VMMap object representing the process memory map"""

    def set_vmmap(self, mapfile):
        """
        Set the vmmap CSV file containing the VM mapping for the process
        that generated the trace, as obtained from procstat or libprocstat
        """
        self.vmmap = VMMap(mapfile)

    def build_dataset(self):
        super(AddressMapPlot, self).build_dataset()

        highmap = {}
        logger.info("Search for capability manipulations in high userspace memory")
        for node in self.dataset.vertices():
            data = self.dataset.vp.data[node]
            if data.cap.base > 0x161000000:
                if data.pc not in highmap:
                    highmap[data.pc] = node
                    logger.info("found high userspace entry %s, pc:0x%x", data, data.pc)

    def plot(self):
        """
        Create the address-map plot
        """

        fig = plt.figure(figsize=(15,10))
        ax = fig.add_axes([0.05, 0.15, 0.9, 0.80,],
                          projection="custom_addrspace")

        dataset_progress = ProgressPrinter(self.dataset.num_vertices(),
                                           desc="Adding nodes")
        for item in self.dataset.vertices():
            data = self.dataset.vp.data[item]
            self.patch_builder.inspect(data)
            self.range_builder.inspect(data)
            dataset_progress.advance()
        dataset_progress.finish()

        view_box = self.patch_builder.get_bbox()
        xmin = view_box.xmin * 0.98
        xmax = view_box.xmax * 1.02
        ymin = view_box.ymin * 0.98
        ymax = view_box.ymax * 1.02

        if self.vmmap:
            self.vmmap_patch_builder.params(y_max=ymax)
            for vme in self.vmmap:
                self.vmmap_patch_builder.inspect(vme)
                self.range_builder.inspect_range(Range(vme.start, vme.end))

        logger.debug("Nodes %d, ranges %d", self.dataset.num_vertices(),
                     len(self.range_builder.ranges))

        for collection in self.patch_builder.get_patches():
            ax.add_collection(collection)
        ax.set_omit_ranges(self.range_builder.get_omit_ranges())
        if self.vmmap:
            for collection in self.vmmap_patch_builder.get_patches():
                ax.add_collection(collection)
            for label in self.vmmap_patch_builder.get_annotations():
                ax.add_artist(label)

        logger.debug("X limits: (%d, %d)", xmin, xmax)
        ax.set_xlim(xmin, xmax)
        logger.debug("Y limits: (%d, %d)", ymin, ymax)
        y_pad = ymax * 0.02
        ax.set_ylim(ymin - y_pad, ymax + y_pad)
        # manually set xticks based on the vmmap if we can
        if self.vmmap:
            start_ticks = [vme.start for vme in self.vmmap]
            end_ticks = [vme.end for vme in self.vmmap]
            ticks = sorted(start_ticks + end_ticks)
            # current_ticks = ax.get_ticks()
            logger.debug("address map ticks %s", ["0x%x" % t for t in ticks])
            ax.set_xticks(ticks)

        ax.invert_yaxis()
        ax.legend(*self.patch_builder.get_legend(), loc="best")
        ax.set_xlabel("Virtual Address")
        ax.set_ylabel("Time (millions of cycles)")

        logger.debug("Plot build completed")
        plt.savefig(self._get_plot_file())
        return fig