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

import logging
import numpy as np

from matplotlib import transforms

from ..core import RangeSet, Range

logger = logging.getLogger(__name__)

class OmitRangeSetBuilder:
    """
    The rangeset generator creates the ranges of address-space in
    which we are not interested.
    """

    def __init__(self):
        self.ranges = RangeSet()
        """List of uninteresting ranges of address-space."""

        self.size_limit = 2**12
        """Minimum distance between omitted address-space ranges."""

        # omit everything if there is nothing to show
        self.ranges.append(Range(0, np.inf, Range.T_OMIT))

    def __iter__(self):
        """Allow convenient iteration over the ranges in the builder."""
        return iter(self.ranges)

    def _update_regions(self, node_range):
        """
        Handle the insertion of a new address range to :attr:`ranges`
        by merging overlapping or contiguous ranges.
        The behaviour is modified by :attr:`size_limit`.

        :param node_range: Range specifying the new region
        :type node_range: :class:`cheriplot.core.Range`
        """
        overlap = self.ranges.match_overlap_range(node_range)
        for r in overlap:
            # 4 possible situations for range (R)
            # and node_range (NR):
            # i) NR completely contained in R
            # ii) R completely contained in NR
            # iii) NR crosses the start or iv) the end of R
            if (node_range.start >= r.start and node_range.end <= r.end):
                # (i) split R
                del self.ranges[self.ranges.index(r)]
                r_left = Range(r.start, node_range.start, Range.T_OMIT)
                r_right = Range(node_range.end, r.end, Range.T_OMIT)
                if r_left.size >= self.size_limit:
                    self.ranges.append(r_left)
                if r_right.size >= self.size_limit:
                    self.ranges.append(r_right)
            elif (node_range.start <= r.start and node_range.end >= r.end):
                # (ii) remove R
                del self.ranges[self.ranges.index(r)]
            elif node_range.start < r.start:
                # (iii) resize range
                r.start = node_range.end
                if r.size < self.size_limit:
                    del self.ranges[self.ranges.index(r)]
            elif node_range.end > r.end:
                # (iv) resize range
                r.end = node_range.start
                if r.size < self.size_limit:
                    del self.ranges[self.ranges.index(r)]

    def inspect(self, data):
        """
        Inspect a data item and update internal
        set of ranges.

        This is intended to be overridden by subclasses.

        :param data: a item of the dataset to be processed
        :type data: object
        """
        return

    def get_omit_ranges(self):
        """
        Return an array of address ranges that do not contain
        interesting data evaluated by :meth:`inspect`.

        This is intended to be overridden by subclasses.

        :return: a list of (start, end) pairs defining each address
        range that should be considered uninteresting
        :rtype: iterable with shape Nx2
        """
        return [[r.start, r.end] for r in self.ranges]


class PatchBuilder:
    """
    The patch generator build the matplotlib patches for each
    dataset item
    """

    def __init__(self):

        self._bbox = transforms.Bbox.from_bounds(0, 0, 0, 0)
        """Bounding box of the artists in the collections."""

    def inspect(self, data):
        """
        Inspect a data item and update internal
        set of patches.

        This is intended to be overridden by subclasses.

        :param data: a item of the dataset to be processed
        :type data: object
        """
        return

    def get_patches(self):
        """
        Return a list of patches to draw for the data
        evaluated by :meth:`inspect`.

        This is intended to be overridden by subclasses.

        :return: a list of matplotlib artists that will be added to
        the Axes
        :rtype: iterable of :class:`matplotlib.artist.Artist`
        """
        return []

    def get_bbox(self):
        """
        Return the bounding box of the data produced, this is useful
        to get the limits in the X and Y of the data.

        :return: a bounding box containing all the artists returned by
        :meth:`get_patches`
        :rtype: :class:`matplotlib.transforms.Bbox`
        """
        return self._bbox

    def get_legend(self):
        """
        Generate legend for the patches produced.

        :return: a 2-tuple that can be used as Axes.legend arguments
        :rtype: tuple
        """
        return None


class PickablePatchBuilder(PatchBuilder):
    """
    Patch builder with additional support for picking
    the objects from the canvas.
    """

    def __init__(self, figure, dataset):
        super(PickablePatchBuilder, self).__init__()
        self._figure = figure
        """The figure used to register the event handler."""

        self._dataset = dataset
        """
        The plot dataset is needed to lookup data associated
        with the item picked in the UI.
        """

        self._figure.canvas.mpl_connect("button_release_event", self.on_click)

    def on_click(self, event):
        """
        Handle the click event on the canvas to check which object is being
        selected.
        We do not use the matplotlib "pick_event" because for collections it
        scans the whole collection to find the artist, we may want to do it
        faster (but can still call the picker on the collection patches).
        Also matplotlib does not allow to bind external data
        (e.g. the graph node) to the object so we would have to do
        that here anyway.

        This is intended to be overridden by subclasses.
        """
        return
