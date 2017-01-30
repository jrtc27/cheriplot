#-
# Copyright (c) 2017 Alfredo Mazzinghi
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

from itertools import chain

from matplotlib import pyplot as plt
from matplotlib import text

from cheriplot.utils import ProgressPrinter
from cheriplot.core.addrspace_axes import Range
from cheriplot.core.vmmap import VMMap
from cheriplot.plot.provenance.provenance_plot import PointerProvenancePlot

logger = logging.getLogger(__name__)

class CapSizeHistogramPlot(PointerProvenancePlot):
    """
    Vertical bar plot showing a bar for each mapped region of
    memory in the executable.
    Each vertical bar is subdivided in bins showing the amount
    of capabilities of size X referencing something in that mapped region.
    The vertical bars have fixed height, representing the 100% of the pointers
    in that region, the size of the bins is therefore the percentage of pointers
    to that region of size X.

    Variants:
    - remove roots, only keep globals (cfromptr)
    """

    def __init__(self, *args, **kwargs):
        super(CapSizeHistogramPlot, self).__init__(*args, **kwargs)

        self.fig, self.ax = self.init_axes()

        self.vmmap = None
        """VMMap object representing the process memory map."""

        self.vm_histograms = []
        """
        List of histograms for each vmmap entry. Each entry is
        a tuple (hist, bin_edges)
        """

        self.n_bins = list(range(0, 41, 10)) + [64]
        """Bin edges for capability size, notice that the size is log2."""

    def init_axes(self):
        """
        Build the figure and axes for the plot
        XXX move this to the Plot base class
        """
        fig = plt.figure(figsize=(15,10))
        ax = fig.add_axes([0.05, 0.15, 0.9, 0.80,],
                          projection="custom_addrspace")
        return (fig, ax)

    def set_vmmap(self, mapfile):
        """
        Use tha CSV file for the memory mapping, later we will
        switch to a dynamic vmmap extracted from the trace.
        """
        self.vmmap = VMMap(mapfile)

    def plot(self):
        """
        Make the vertical bar plot based on the processed dataset
        """
        
        histogram_data = np.array(self.vm_histograms)

        # 10 is the number of bins, just test it with 10 for now
        bottom = np.zeros(len(self.vm_histograms))
        positions = range(1, 2*len(self.vm_histograms) + 1, 2)
        legend_handles = []
        legend_labels = []
        for bin_idx, bin_limit in enumerate(self.n_bins[1:]):
            color = np.random.rand(3,1)
            bar_slices = self.ax.bar(positions, histogram_data[:,bin_idx],
                                     bottom=bottom, color=color)
            legend_handles.append(bar_slices[0])            
            legend_labels.append("Size: 2^%d" % bin_limit)
            bottom = bottom + histogram_data[:,bin_idx]
        # place labels
        ticklabels = []
        for idx, entry in enumerate(self.vmmap):
            path = str(entry.path).split("/")[-1] if str(entry.path) else ""
            label = "%s (%s)" % (path, entry.perms)
            ticklabels.append(label)
        self.ax.set_xticks(np.array(positions) + 0.5)
        self.ax.set_xticklabels(ticklabels, rotation="vertical")
        self.ax.set_xlim(0, positions[-1] + 1)
        self.ax.set_ylim(0, 1.5)
        self.ax.legend(legend_handles, legend_labels)

        logger.debug("Plot build completed")
        plt.savefig(self._get_plot_file())


class CapSizeCreationPlot(CapSizeHistogramPlot):
    """
    Histogram plot that takes into account capabilities at creation time.
    The address space is split in chunks according to the VM map of the
    process. For each chunk, the set of capabilities that can be
    dereferenced in the chunk is computed. Note that the same capability may
    be counted in multiple chunks if it spans multiple VM map entries (eg DDC)
    From each set an histogram is generated and the bin count is used to produce
    the bar chart.
    """

    def build_dataset(self):
        """Process the provenance graph to extract histogram data."""
        super(CapSizeCreationPlot, self).build_dataset()

        # indexes in the vmmap and in the vm_histograms are
        # the same.
        vm_ranges = [Range(v.start, v.end) for v in self.vmmap]

        histogram_input = [[] for _ in range(len(vm_ranges))]

        progress = ProgressPrinter(self.dataset.num_vertices(),
                                   desc="Sorting capability references")
        logger.debug("Vm ranges %s", vm_ranges)
        for node in self.dataset.vertices():
            data = self.dataset.vp.data[node]

            for idx, r in enumerate(vm_ranges):
                if Range(data.cap.base, data.cap.bound) in r:
                    histogram_input[idx].append(data.cap.length)
            progress.advance()
        progress.finish()

        for data in histogram_input:
            logger.debug("hist entry len %d", len(data))
            data = np.array(data) + 1
            data = np.log2(data)
            logger.debug("hist entry log len %d", len(data))
            h, b = np.histogram(data, bins=self.n_bins)
            logger.debug("hist entry bins %d, tot:%d", len(h), np.sum(h))
            # append normalized histogram to the list
            self.vm_histograms.append(h / np.sum(h))


class CapSizeDerefPlot(CapSizeHistogramPlot):
    """
    Histogram plot that takes into account capabilities at dereference time.
    The address space is split in the same was as in 
    :class:`CapSizeCreationPlot` but the each capability is assigned to
    a memory-mapped region based on its offset when it is dereferenced.
    Note that there is an amount of overcounting due to locations that
    are heavily accessed.
    """

    def build_dataset(self):
        """Process the provenance graph to extract histogram data."""
        super(CapSizeDerefPlot, self).build_dataset()

        # indexes in the vmmap and in the vm_histograms are
        # the same.
        vm_ranges = [Range(v.start, v.end) for v in self.vmmap]

        histogram_input = [[] for _ in range(len(vm_ranges))]

        progress = ProgressPrinter(self.dataset.num_vertices(),
                                   desc="Sorting capability references")
        for node in self.dataset.vertices():
            data = self.dataset.vp.data[node]
            # iterate over every dereference of the node
            for addr in chain(data.deref["load"], data.deref["store"]):
                # check in which vm-entry the address is
                for idx, r in enumerate(vm_ranges):
                    if addr in r:
                        histogram_input[idx].append(data.cap.length)
            progress.advance()
        progress.finish()

        for data in histogram_input:
            data = np.array(data) + 1
            data = np.log2(data)
            h, b = np.histogram(data, bins=self.n_bins)
            total_addrs = np.sum(h)
            if total_addrs == 0:
                # no dereferences in this region
                self.vm_histograms.append(h)
            else:
                # append normalized histogram to the list
                self.vm_histograms.append(h / total_addrs)


class CapSizeCallPlot(CapSizeHistogramPlot):
    """
    Histogram plot that takes into account capabilities that are called.
    Same as :class:`CapSizeCreationPlot` but the capabilities are
    taken at call-time.
    """

    def build_dataset(self):
        """Process the provenance graph to extract histogram data."""
        super(CapSizeCallPlot, self).build_dataset()

        # indexes in the vmmap and in the vm_histograms are
        # the same.
        vm_ranges = [Range(v.start, v.end) for v in self.vmmap]

        histogram_input = [[] for _ in range(len(vm_ranges))]

        progress = ProgressPrinter(self.dataset.num_vertices(),
                                   desc="Sorting capability references")
        for node in self.dataset.vertices():
            data = self.dataset.vp.data[node]
            # iterate over every dereference of the node
            for addr in data.deref["call"]:
                # check in which vm-entry the address is
                for idx, r in enumerate(vm_ranges):
                    if addr in r:
                        histogram_input[idx].append(data.cap.length)
            progress.advance()
        progress.finish()

        for data in histogram_input:
            data = np.array(data) + 1
            data = np.log2(data)
            h, b = np.histogram(data, bins=self.n_bins)
            total_addrs = np.sum(h)
            if total_addrs == 0:
                # no dereferences in this region
                self.vm_histograms.append(h)
            else:
                # append normalized histogram to the list
                self.vm_histograms.append(h / total_addrs)